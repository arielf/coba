import re

from itertools import repeat
from typing import Any, Dict, Union, Sequence, Optional, Tuple, List
from coba.backports import Literal

from coba.pipes import Flatten
from coba.exceptions import CobaException
from coba.utilities import PackageChecker
from coba.environments import Context, Action

from coba.learners.primitives import Learner, Probs, Info

Feature       = Union[str,int,float]
Features      = Union[Feature, Sequence[Feature], Dict[str,Feature]]
Namespaces    = Dict[str,Features]
VW_Features   = Sequence[Union[str,int,Tuple[str,Union[int,float]],Tuple[int,Union[int,float]]]]
VW_Namespaces = Dict[str,VW_Features]

class VowpalMediator:
    """A class to handle all communication between Coba and VW."""

    def __init__(self) -> None:
        self._vw = None
        self._ns_offsets: Dict[str,int] = {}
        self._curr_ns_offset = 0

        PackageChecker.vowpalwabbit('VowpalMediator.__init__')

    @property
    def is_initialized(self) -> bool:
        """Indicate whether init_learner has been called previously."""
        return self._vw is not None

    def init_learner(self, args:str, label_type: int) -> 'VowpalMediator':
        """Create a VW learner from a command line arg string.
        
        Args:
            args: The command line arg string to use for VW learner creation.
            label_type: The label type this VW learner will take.
                - 1 : `simple`__
                - 2 : `multiclass`__
                - 3 : `cost sensitive`__
                - 4 : `contextual bandit`__
                - 5 : max (deprecated)
                - 6 : `conditional contextual bandit`__
                - 7 : `slates`__
                - 8 : `continuous actions`__

        __ https://github.com/VowpalWabbit/vowpal_wabbit/wiki/Input-format#simple
        __ https://github.com/VowpalWabbit/vowpal_wabbit/wiki/Input-format#multiclass
        __ https://github.com/VowpalWabbit/vowpal_wabbit/wiki/Input-format#cost-sensitive
        __ https://github.com/VowpalWabbit/vowpal_wabbit/wiki/Input-format#contextual-bandit
        __ https://github.com/VowpalWabbit/vowpal_wabbit/wiki/Conditional-Contextual-Bandit#vw-text-format
        __ https://github.com/VowpalWabbit/vowpal_wabbit/wiki/Slates#text-format
        __ https://github.com/VowpalWabbit/vowpal_wabbit/wiki/CATS,-CATS-pdf-for-Continuous-Actions#vw-text-format
        """
        from vowpalwabbit import pyvw, __version__
        
        if self._vw is not None:
            raise CobaException("We cannot initilaize a VW learner twice in a single mediator.")

        self._version = __version__
        self._vw = pyvw.Workspace(args) if __version__[0] == '9' else pyvw.vw(args)
        self._label_type = pyvw.LabelType(label_type) if __version__[0] == '9' else label_type
        self._example_type = pyvw.Example if __version__[0] == '9' else pyvw.example

        return self

    def predict(self, example: Any) -> Any:
        """Predict for an example created by the mediator."""
        pred = self._vw.predict(example)
        self._vw.finish_example(example)
        return pred

    def learn(self, example: Any) -> None:
        """Learn for an example created by the mediator."""
        self._vw.learn(example)
        self._vw.finish_example(example)

    def make_example(self, namespaces: Namespaces, label:Optional[str]) -> Any:
        """Create a VW example.
        
        Args:
            ns: The features grouped by namespace in this example.
            label: An optional label (required if this example will be used for learning).
        """
        ns = dict(self._prep_namespaces(namespaces))
        ex = self._example_type(self._vw, ns, self._label_type)
        if label is not None: ex.set_label_string(label)

        ex.setup_example()

        return ex

    def make_examples(self, shared: Namespaces, separates: Sequence[Namespaces], labels:Optional[Sequence[str]]) -> Sequence[Any]:
        """Create a list of VW examples.
        
        Args:
            shared: The features grouped by namespace in this example.
            label: An optional label (required if this example will be used for learning).
        """

        labels       = repeat(None) if labels is None else labels
        vw_shared    = dict(self._prep_namespaces(shared))
        vw_separates = list(map(dict,map(self._prep_namespaces,separates)))

        examples = []
        for vw_separate, label in zip(vw_separates,labels):
            ex = self._example_type(self._vw, {**vw_shared, **vw_separate}, self._label_type)
            if label: ex.set_label_string(label)
            ex.setup_example()
            examples.append(ex)

        return examples

    def _prep_namespaces(self, namespaces: Namespaces) -> VW_Namespaces:
        """Turn a collection of coba formatted namespaces into VW format."""        

        #the strange type checks below were faster than traditional methods when performance testing
        for ns, feats in namespaces.items():
            if not feats and feats != 0 and feats != "":
                continue
            elif feats.__class__ is str:
                yield (ns, [f"{self._get_ns_offset(ns,1)}={feats}"])
            elif feats.__class__ is int or feats.__class__ is float:
                yield (ns, [(self._get_ns_offset(ns,1), feats)])
            else:
                feats = feats.items() if feats.__class__ is dict else enumerate(feats,self._get_ns_offset(ns,len(feats)))
                yield (ns, [f"{k}={v}" if v.__class__ is str else (k, v) for k,v in feats if v!= 0])

    def _get_ns_offset(self, namespace:str, length:int) -> Sequence[int]:
        value = self._ns_offsets.setdefault(namespace, self._curr_ns_offset)
        self._curr_ns_offset += length
        return value

    def __reduce__(self):
        return (VowpalMediator, ())

class VowpalArgsLearner(Learner):
    """A friendly wrapper around Vowpal Wabbit's python interface to support CB learning.
    
    Remarks: 
        This learner requires that the Vowpal Wabbit package be installed. This package can be
        installed via `pip install vowpalwabbit`. To learn more about solving contextual bandit
        problems with Vowpal Wabbit see `here`__ and `here`__.

    __ https://vowpalwabbit.org/tutorials/contextual_bandits.html
    __ https://github.com/VowpalWabbit/vowpal_wabbit/wiki/Contextual-Bandit-algorithms
    """

    @staticmethod
    def make_args(
        options: Sequence[str], 
        noconstant: bool,
        interactions: Sequence[str], 
        ignore_linear:Sequence[str],
        seed: Optional[int], 
        **kwargs) -> str:
        """Turn settings into a VW command line string.

        Args:
            options: A sequence of string values that represent VW CLI options.
            noconstant: Indicates if constant term should be included in the VW features.
            interactions: A sequence of namespace interactions to use during learning.
            ignore_linear: A sequence of linear namespaces to ignore during learning.
            seed: A random number generator seed to make sure VW behaves consistently.
            kwargs: Any number of additional options to add to the arg string.
        """

        options = list(filter(None,options))

        if noconstant:
            options.append(f"--noconstant")

        for interaction in interactions:
            options.append(f"--interactions {interaction}")

        for ignore in ignore_linear:
            options.append(f"--ignore_linear {ignore}")

        if seed is not None:
            options.append(f"--random_seed {seed}")

        kwargs['quiet'] = kwargs.get('quiet',True)

        for k,v in kwargs.items():
            if v is not False:
                k = ("-" if len(k)==1 else "--") + k
                options.append(k if (v is None or v == True) else f"{k} {v}")

        return " ".join(options)

    def __init__(self, args: str = "--cb_explore_adf --epsilon 0.05 --interactions ax --interactions axx --ignore_linear x --random_seed 1 --quiet", vw: VowpalMediator = None) -> None:
        """Instantiate a VowpalArgsLearner.

        Args:
            args: Command line arguments to instantiate a Vowpal Wabbit contextual bandit learner. For 
                examples and documentation on how to instantiate VW learners from command line arguments 
                see `here`__. We require that either cb, cb_adf, cb_explore, or cb_explore_adf is used. 
                When we format examples for VW context features are placed in the 'x' namespace and action 
                features, when relevant, are placed in the 'a' namespace.
            vw: A mediator able to communicate with VW. This should not need to ever be changed. 
        __ https://github.com/VowpalWabbit/vowpal_wabbit/wiki/Contextual-Bandit-algorithms
        """

        if "--cb" not in args: 
            raise CobaException("VowpalArgsLearner was instantiated without a cb flag. One of the cb flags must be defined.")

        self._args    = args
        self._explore = "--cb_explore" in args
        self._adf     = "--cb_adf"     in args or "--cb_explore_adf" in args

        self._n_actions = None
        self._actions   = None

        try:
            self._n_actions = int(re.match("--cb.*?\s+(\d*)\s*-?.*$", args).group(1))
        except:
            pass

        self._vw = vw or VowpalMediator()

        if self._adf or self._n_actions is not None:
            self._vw.init_learner(args, 4)

    @property
    def params(self) -> Dict[str, Any]:
        return {"family": "vw", 'args': self._args.replace("--quiet","").strip()}

    def predict(self, context: Context, actions: Sequence[Action]) -> Tuple[Probs, Info]:

        if not self._adf and not self._actions:
            self._actions = actions

        if not self._vw.is_initialized: #this should only be true for not adf with no actions given
            self._n_actions = len(actions)
            args            = self._args.replace('--cb_explore','').replace('--cb','')
            args            = f"--cb_explore {len(actions)} " if self._explore else f"--cb {len(actions)} " + args
            args            = args.strip()
            self._vw.init_learner(args,4)

        if not self._adf and actions != self._actions:
            raise CobaException("Actions are only allowed to change between predictions when using `adf`.")

        if not self._adf and len(actions) != self._n_actions:
            raise CobaException("The number of actions doesn't match the `--cb` action count given in args.")

        info = (actions if self._adf else self._actions)

        context = {'x':self._flat(context)}
        adfs    = None if not self._adf else [{'a':self._flat(action)} for action in actions]

        if self._adf and self._explore:
            probs = self._vw.predict(self._vw.make_examples(context, adfs, None))

        if self._adf and not self._explore:
            losses    = self._vw.predict(self._vw.make_examples(context,adfs, None))
            min_loss  = min(losses)
            min_bools = [s == min_loss for s in losses]
            min_count = sum(min_bools)
            probs     = [ int(min_indicator)/min_count for min_indicator in min_bools ]
        
        if not self._adf and self._explore:
            probs = self._vw.predict(self._vw.make_example(context, None))
            
        if not self._adf and not self._explore:
            index = self._vw.predict(self._vw.make_example(context, None))
            probs = [ int(i==index) for i in range(1,len(actions)+1) ]

        return probs, info

    def learn(self, context: Context, action: Action, reward: float, probability: float, info: Info) -> None:

        if not self._vw.is_initialized:
            raise CobaException("When using `cb  without `adf` predict must be called before learn to initialize the vw learner")

        actions = info
        labels  = self._labels(actions, action, reward, probability)
        label   = labels[actions.index(action)]

        context = {'x':self._flat(context)}
        adfs    = None if not self._adf else [{'a':self._flat(action)} for action in actions]

        if self._adf:
            self._vw.learn(self._vw.make_examples(context, adfs, labels))
        else:
            self._vw.learn(self._vw.make_example(context, label))

    def _labels(self,actions,action,reward:float,prob:float) -> Sequence[Optional[str]]:
        return [ f"{i+1}:{round(-reward,5)}:{round(prob,5)}" if a == action else None for i,a in enumerate(actions)]

    def _flat(self,features:Any) -> Any:        
        return list(Flatten().filter([features]))[0]

    def __reduce__(self):
        return (VowpalArgsLearner, (self._args, self._vw) )

class VowpalEpsilonLearner(VowpalArgsLearner):
    """A wrapper around VowpalArgsLearner that provides more documentation. For more 
        information on the types of exploration algorithms availabe in VW see `here`__.

        __ https://github.com/VowpalWabbit/vowpal_wabbit/wiki/Contextual-Bandit-algorithms
    """

    def __init__(self,
        epsilon: float = 0.05,
        features: Sequence[str] = [1,'a','ax','axx'],
        seed: Optional[int] = 1,
        **kwargs) -> None:
        """Instantiate a VowpalEpsilonLearner.

        Args:
            epsilon: The probability that we will explore instead of exploit.
            features: A list of namespaces and interactions  to use when learning reward functions.
            seed: The seed used by VW to generate any necessary random numbers.
        """

        options       = [ "--cb_explore_adf", f"--epsilon {epsilon}" ]
        noconstant    = sum([f for f in features if isinstance(f,(int,float))]) == 0
        ignore_linear = set(['x','a'])-set(features)
        interactions  = [f for f in features if isinstance(f,str) and len(f) > 1]
        super().__init__(VowpalArgsLearner.make_args(options, noconstant, interactions, ignore_linear, seed, **kwargs))

class VowpalSoftmaxLearner(VowpalArgsLearner):
    """A wrapper around VowpalArgsLearner that provides more documentation. For more
        information on the types of exploration algorithms availabe in VW see `here`__.

        __ https://github.com/VowpalWabbit/vowpal_wabbit/wiki/Contextual-Bandit-algorithms
    """

    def __init__(self,
        softmax: float=10,
        features: Sequence[str] = [1,'a','ax','axx'],
        seed: Optional[int] = 1,

        **kwargs) -> None:
        """Instantiate a VowpalSoftmaxLearner.

        Args:
            softmax: An exploration parameter with 0 indicating predictions should be completely random
                and infinity indicating that predictions should be greedy. For more information see `lambda`__.
            features: A list of namespaces and interactions  to use when learning reward functions.
            seed: The seed used by VW to generate any necessary randomness.
        
        __ https://github.com/VowpalWabbit/vowpal_wabbit/wiki/Contextual-Bandit-algorithms
        """

        options       = [ "--cb_explore_adf", "--softmax", f"--lambda {softmax}" ]
        noconstant    = sum([f for f in features if isinstance(f,(int,float))]) == 0
        ignore_linear = set(['x','a'])-set(features)
        interactions  = [f for f in features if isinstance(f,str) and len(f) > 1]
        super().__init__(VowpalArgsLearner.make_args(options, noconstant, interactions, ignore_linear, seed, **kwargs))

class VowpalBagLearner(VowpalArgsLearner):
    """A wrapper around VowpalArgsLearner that provides more documentation. For more 
        information on the types of exploration algorithms availabe in VW see `here`__.

        __ https://github.com/VowpalWabbit/vowpal_wabbit/wiki/Contextual-Bandit-algorithms
    """

    def __init__(self,
        bag: int = 5,
        features: Sequence[str] = [1,'a','ax','axx'],
        seed: Optional[int] = 1,
        **kwargs) -> None:
        """Instantiate a VowpalBagLearner.

        Args:
            bag: This value determines the number of policies which will be learned and must be greater
                than 0. Each policy is trained using bootstrap aggregation, making each policy unique. During
                prediction a random policy will be selected according to a uniform distribution and followed.
            features: A list of namespaces and interactions  to use when learning reward functions.
            seed: The seed used by VW to generate any necessary random numbers.
        """

        options       = [ "--cb_explore_adf", f"--bag {bag}" ]
        noconstant    = sum([f for f in features if isinstance(f,(int,float))]) == 0
        ignore_linear = set(['x','a'])-set(features)
        interactions  = [f for f in features if isinstance(f,str) and len(f) > 1]
        super().__init__(VowpalArgsLearner.make_args(options, noconstant, interactions, ignore_linear, seed, **kwargs))

class VowpalCoverLearner(VowpalArgsLearner):
    """A wrapper around VowpalArgsLearner that provides more documentation. For more 
        information on the types of exploration algorithms availabe in VW see `here`__.

    For more information on this algorithm see Agarwal et al. (2014).

    References:
        Agarwal, Alekh, Daniel Hsu, Satyen Kale, John Langford, Lihong Li, and Robert Schapire. "Taming 
        the monster: A fast and simple algorithm for contextual bandits." In International Conference on 
        Machine Learning, pp. 1638-1646. 2014.

        __ https://github.com/VowpalWabbit/vowpal_wabbit/wiki/Contextual-Bandit-algorithms
    """

    def __init__(self, 
        cover: int = 5,
        features: Sequence[str] = [1,'a','ax','axx'],
        seed: Optional[int] = 1,
        **kwargs) -> None:
        """Instantiate a VowpalCoverLearner.

        Args:
            cover: The number of policies which will be learned (must be greater than 0).
            features: A list of namespaces and interactions  to use when learning reward functions.
            seed: The seed used by VW to generate any necessary random numbers.
        """

        options       = [ "--cb_explore_adf", f"--cover {cover}" ]
        noconstant    = sum([f for f in features if isinstance(f,(int,float))]) == 0
        ignore_linear = set(['x','a'])-set(features)
        interactions  = [f for f in features if isinstance(f,str) and len(f) > 1]
        super().__init__(VowpalArgsLearner.make_args(options, noconstant, interactions, ignore_linear, seed, **kwargs))

class VowpalRegcbLearner(VowpalArgsLearner):
    """A wrapper around VowpalArgsLearner that provides more documentation. For more 
        information on the types of exploration algorithms availabe in VW see `here`__.

    References:
        Foster, D., Agarwal, A., Dudik, M., Luo, H. & Schapire, R.. (2018). Practical Contextual 
        Bandits with Regression Oracles. Proceedings of the 35th International Conference on Machine 
        Learning, in Proceedings of Machine Learning Research 80:1539-1548.

        __ https://github.com/VowpalWabbit/vowpal_wabbit/wiki/Contextual-Bandit-algorithms
    """

    def __init__(self,
        mode: Literal["optimistic","elimination"] = "elimination",
        features: Sequence[str] = [1,'a','ax','axx'],
        seed: Optional[int] = 1,
        **kwargs) -> None:
        """Instantiate a VowpalRegcbLearner.

        Args:
            mode: Indicates whether exploration should only predict the optimal upper bound action or
                should use an elimination technique to remove actions that no longer seem plausible
                and pick randomly from the remaining actions.
            features: A list of namespaces and interactions  to use when learning reward functions.
            seed: The seed used by VW to generate any necessary random numbers.
        """

        options       = [ "--cb_explore_adf", "--regcb" if mode=="elimination" else "--regcbopt" ]
        noconstant    = sum([f for f in features if isinstance(f,(int,float))]) == 0
        ignore_linear = set(['x','a'])-set(features)
        interactions  = [f for f in features if isinstance(f,str) and len(f) > 1]
        super().__init__(VowpalArgsLearner.make_args(options, noconstant, interactions, ignore_linear, seed, **kwargs))

class VowpalSquarecbLearner(VowpalArgsLearner):
    """A wrapper around VowpalArgsLearner that provides more documentation. For more 
        information on the types of exploration algorithms availabe in VW see `here`__.

    References:
        Foster, D.& Rakhlin, A.. (2020). Beyond UCB: Optimal and Efficient Contextual Bandits with Regression 
        Oracles. Proceedings of the 37th International Conference on Machine Learning, in Proceedings of Machine 
        Learning Research 119:3199-3210.

        __ https://github.com/VowpalWabbit/vowpal_wabbit/wiki/Contextual-Bandit-algorithms
    """

    def __init__(self,
        mode: Literal["standard","elimination"] = "standard",
        gamma_scale: float = 10,
        features: Sequence[str] = [1,'a','ax','axx'],
        seed: Optional[int] = 1,
        **kwargs) -> None:
        """Instantiate a VowpalSquarecbLearner.

        Args:
            mode: Indicates iwhether all actions should be considered for exploration on each step or actions
                which no longer seem plausible should be eliminated.
            gamma_scale: Controls how quickly squarecb exploration converges to a greedy policy. The larger the
                gamma_scale the faster the algorithm will converge to a greedy policy. This value is the same
                as gamma in the original paper.
            features: A list of namespaces and interactions to use when learning reward functions.
            seed: The seed used by VW to generate any necessary random numbers.
        """

        options = [
            "--cb_explore_adf",
            "--squarecb",
            f"--gamma_scale {gamma_scale}",
            "" if mode != "elimination" else "--elim"
        ]
        
        noconstant    = sum([f for f in features if isinstance(f,(int,float))]) == 0
        ignore_linear = set(['x','a'])-set(features)
        interactions  = [f for f in features if isinstance(f,str) and len(f) > 1]
        super().__init__(VowpalArgsLearner.make_args(options, noconstant, interactions, ignore_linear, seed, **kwargs))

class VowpalOffPolicyLearner(VowpalArgsLearner):
    """A wrapper around VowpalArgsLearner that provides more documentation. For more 
        information on the types of exploration algorithms availabe in VW see `here`__.

        This wrapper in particular performs policy learning without any exploration. This is
        only correct when training examples come from a logging policy so that any exploration 
        on our part is ignored.

        __ https://github.com/VowpalWabbit/vowpal_wabbit/wiki/Contextual-Bandit-algorithms
    """

    def __init__(self,
        features: Sequence[str] = [1,'a','ax','axx'],
        seed: Optional[int] = 1,
        **kwargs) -> None:
        """Instantiate a VowpalOffPolicyLearner.

        Args:
            features: A list of namespaces and interactions  to use when learning reward functions.
            seed: The seed used by VW to generate any necessary random numbers.
        """

        options       = ["--cb_adf"]
        noconstant    = sum([f for f in features if isinstance(f,(int,float))]) == 0
        ignore_linear = set(['x','a'])-set(features)
        interactions  = [f for f in features if isinstance(f,str) and len(f) > 1]
        super().__init__(VowpalArgsLearner.make_args(options, noconstant, interactions, ignore_linear, seed, **kwargs))
