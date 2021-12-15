import math
import collections.abc

from itertools import chain, repeat, count
from typing import Sequence, Dict, Any, Iterable, Union, List, Callable, Tuple, overload

from coba.pipes import Source, Filter  
from coba.pipes import DiskIO, MemoryIO
from coba.pipes import CsvReader, ArffReader, LibSvmReader, ManikReader, Structure
from coba.random import CobaRandom
from coba.encodings import InteractionsEncoder, OneHotEncoder, IdentityEncoder
from coba.exceptions import CobaException

from coba.environments.primitives import Context, Action, SimulatedEnvironment, SimulatedInteraction

T_Dense_Feat  = Sequence[Any]
T_Sparse_Feat = Dict[Any,Any]
T_Dense_Rows  = Iterable[Tuple[T_Dense_Feat,Any]]
T_Sparse_Rows = Iterable[Tuple[T_Sparse_Feat,Any]]

class MemorySimulation(SimulatedEnvironment):
    """A Simulation implementation created from in memory sequences of contexts, actions and rewards."""

    def __init__(self, interactions: Sequence[SimulatedInteraction]) -> None:
        """Instantiate a MemorySimulation.

        Args:
            interactions: The sequence of interactions in this simulation.
        """
        self._interactions = interactions

    @property
    def params(self) -> Dict[str, Any]:
        """Paramaters describing the simulation."""
        return {}

    def read(self) -> Iterable[SimulatedInteraction]:
        """Read the interactions in this simulation."""
        return self._interactions

class ClassificationSimulation(SimulatedEnvironment):
    """A simulation created from classification dataset with features and labels.

    ClassificationSimulation turns labeled observations from a classification data set
    into interactions. For each interaction the feature set becomes the context and 
    all possible labels become the actions. Rewards for each interaction are created by 
    assigning a reward of 1 for taking the correct action (i.e., choosing the correct
    label)) and a reward of 0 for taking any other action (i.e., choosing any of the
    incorrect lables).
    """

    @overload
    def __init__(self, examples: Union[T_Dense_Rows,T_Sparse_Rows]) -> None:
        """Instantiate a ClassificationSimulation.

        Args:
            examples: Labeled examples to use when creating the contextual bandit simulation.
        """

    @overload
    def __init__(self, features: Union[Iterable[T_Dense_Feat], Iterable[T_Sparse_Feat]], labels: Iterable[Any]) -> None:
        """Instantiate a ClassificationSimulation.

        Args:
            features: A sequence of features to use as context when creating the contextual bandit simulation.
            labels: A sequence of class labels to use as actions and rewards when creating the contextual bandit simulation
        """

    def __init__(self, *args, **kwargs) -> None:
        """Instantiate a ClassificationSimulation."""

        if len(args) not in [1,2]:
            raise CobaException("We were unable to determine which overloaded constructor to use")

        self._examples = args[0] if len(args) == 1 else zip(args[0],args[1])

    @property
    def params(self) -> Dict[str, Any]:
        """Paramaters describing the simulation."""
        return { }

    def read(self) -> Iterable[SimulatedInteraction]:
        """Read the interactions in this simulation."""

        examples = list(self._examples)

        if examples:

            features,labels = zip(*examples)

            #how can we tell the difference between featurized labels and multilabels????
            #for now we will assume multilables will be passed in as arrays not tuples...
            if not isinstance(labels[0], collections.abc.Hashable):
                labels_flat = list(chain.from_iterable(labels))
            else:
                labels_flat = list(labels)

            reward        = lambda action,label: int(is_label(action,label) or in_multilabel(action,label)) #type: ignore
            is_label      = lambda action,label: action == label #type: ignore
            in_multilabel = lambda action,label: isinstance(label,collections.abc.Sequence) and action in label #type: ignore

            # shuffling so that action order contains no statistical information
            # sorting so that the shuffled values are always shuffled in the same order
            actions  = CobaRandom(1).shuffle(sorted(set(labels_flat))) 
            contexts = features
            rewards  = [ [ reward(action,label) for action in actions ] for label in labels ]

            for c,a,r in zip(contexts, repeat(actions), rewards):
                yield SimulatedInteraction(c,a,rewards=r)

class RegressionSimulation(SimulatedEnvironment):
    """A simulation created from regression dataset with features and labels.
    
    RegressionSimulation turns labeled observations from a regression data set
    into interactions. For each interaction the feature set becomes the context and 
    all possible labels become the actions. Rewards for each interaction are created by 
    assigning a minus absolute error. Rewards are close to zero for taking actions that are 
    closer to the correct action (label) and lower ones for being far from the correct action.
    
    """

    @property
    def params(self) -> Dict[str, Any]:
        """Paramaters describing the simulation."""
        return {}

    @overload
    def __init__(self, examples: Union[T_Dense_Rows,T_Sparse_Rows]) -> None:
        """Instantiate a RegressionSimulation.

        Args:
            examples: Labeled examples to use when creating the contextual bandit simulation.
        """

    @overload
    def __init__(self, features: Union[Iterable[T_Dense_Feat], Iterable[T_Sparse_Feat]], labels: Iterable[float]) -> None:
        """Instantiate a RegressionSimulation.

        Args:
            features: A sequence of features to use as context when creating the contextual bandit simulation.
            labels: A sequence of numeric labels to use as actions and rewards when creating the contextual bandit simulation
        """
    
    def __init__(self, *args, **kwargs) -> None:
        """Instantiate a RegressionSimulation."""

        if len(args) not in [1,2]:
            raise CobaException("We were unable to determine which overloaded constructor to use")
        
        self._examples = args[0] if len(args) == 1 else zip(args[0],args[1])

    def read(self) -> Iterable[SimulatedInteraction]:
        """Read the interactions in this simulation."""
        
        examples = list(self._examples)

        if examples:

            features,labels = zip(*examples)

            reward   = lambda action,label: 1-round(abs(float(action)-float(label)),2)
            contexts = features
            actions  = CobaRandom(1).shuffle(sorted(set(labels)))
            rewards  = [ [ reward(action,label) for action in actions ] for label in labels ]

            for c,a,r in zip(contexts, repeat(actions), rewards):
                yield SimulatedInteraction(c,a,rewards=r)

class LambdaSimulation(SimulatedEnvironment):
    """A Simulation created from lambda functions that generate contexts, actions and rewards.

    Remarks:
        This implementation is useful for creating a simulation from defined distributions.
    """

    def __init__(self,
        n_interactions: int,
        context       : Callable[[int               ],Context         ],
        actions       : Callable[[int,Context       ],Sequence[Action]], 
        reward        : Callable[[int,Context,Action],float           ]) -> None:
        """Instantiate a LambdaSimulation.

        Args:
            n_interactions: How many interactions the LambdaSimulation should have.
            context: A function that should return a context given an index in `range(n_interactions)`.
            actions: A function that should return all valid actions for a given index and context.
            reward: A function that should return the reward for the index, context and action.
        """

        self._interactions: List[SimulatedInteraction] = []

        for i in range(n_interactions):
            _context  = context(i)
            _actions  = actions(i, _context)
            _rewards  = [ reward(i, _context, _action) for _action in _actions]

            self._interactions.append(SimulatedInteraction(_context, _actions, rewards=_rewards))

    @property
    def params(self) -> Dict[str, Any]:
        """Paramaters describing the simulation."""
        return {}

    def read(self) -> Iterable[SimulatedInteraction]:
        """Read the interactions in this simulation."""
        
        return self._interactions

    def __str__(self) -> str:
        return "LambdaSimulation"

class ReaderSimulation(SimulatedEnvironment):

    def __init__(self, 
        reader   : Filter[Iterable[str], Any], 
        source   : Union[str,Source[Iterable[str]]], 
        label_col: Union[str,int]) -> None:
        
        self._reader       = reader
        self._source       = DiskIO(source) if isinstance(source, str) else source
        self._label_column = label_col

    @property
    def params(self) -> Dict[str, Any]:
        """Paramaters describing the simulation."""
        if isinstance(self._source,DiskIO):
            return {"source": str(self._source._filename) }
        elif isinstance(self._source,MemoryIO):
            return {"source": 'memory' }
        else:
            return {"source": self._source.__class__.__name__}

    def read(self) -> Iterable[SimulatedInteraction]:
        """Read the interactions in this simulation."""
        parsed_rows_iter = iter(self._reader.filter(self._source.read()))
        structured_rows = Structure([None, self._label_column]).filter(parsed_rows_iter)

        return ClassificationSimulation(structured_rows).read()

class CsvSimulation(ReaderSimulation):
    def __init__(self, source:Union[str,Source[Iterable[str]]], label_column:Union[str,int], with_header:bool=True) -> None:
        super().__init__(CsvReader(with_header), source, label_column)

    @property
    def params(self) -> Dict[str, Any]:
        """Paramaters describing the simulation."""
        return { "csv": super().params["source"] }

class ArffSimulation(ReaderSimulation):
    def __init__(self, source:Union[str,Source[Iterable[str]]], label_column:Union[str,int]) -> None:
        super().__init__(ArffReader(skip_encoding=[label_column]), source, label_column)

    @property
    def params(self) -> Dict[str, Any]:
        """Paramaters describing the simulation."""
        return { "arff": super().params["source"] }

class LibsvmSimulation(ReaderSimulation):
    def __init__(self, source:Union[str,Source[Iterable[str]]]) -> None:
        super().__init__(LibSvmReader(), source, 0)

    @property
    def params(self) -> Dict[str, Any]:
        """Paramaters describing the simulation."""
        return { "libsvm": super().params["source"] }

class ManikSimulation(ReaderSimulation):
    def __init__(self, source:Union[str,Source[Iterable[str]]]) -> None:
        super().__init__(ManikReader(), source, 0)

    @property
    def params(self) -> Dict[str, Any]:
        """Paramaters describing the simulation."""
        return { "manik": super().params["source"] }

class LinearSyntheticSimulation(LambdaSimulation):
    
    def __init__(self, 
        n_interactions: int=500, 
        n_actions: int=10, 
        n_context_feats:int = 10, 
        n_action_feats:int = 10, 
        r_noise_var:float = 1/1000,
        interactions: Sequence[str] = ["a","xa"],
        seed:int=1) -> None:

        self._n_actions          = n_actions
        self._n_context_features = n_context_feats
        self._n_action_features  = n_action_feats
        self._seed               = seed
        self._r_noise_var        = r_noise_var
        self._X                  = interactions

        rng = CobaRandom(seed)
        X_encoder = InteractionsEncoder(self._X)

        dummy_context = list(range(max(1,n_context_feats)))
        dummy_action  = list(range(n_action_feats)) if n_action_feats else list(range(n_actions))
        feature_count = len(X_encoder.encode(x=dummy_context,a=dummy_action))

        normalize = lambda X: [ rng.random()*x/sum(X) for x in X]
        identity  = lambda n: OneHotEncoder().fit_encode(range(n))

        weights = normalize(rng.randoms(feature_count)) # we normalize weights so that reward will be in [0,1]
        actions = ( [rng.randoms(n_action_feats) for _ in range(n_actions)] for _ in count()) if n_actions else repeat(identity(n_actions))
        A_ident = None if n_action_feats else identity(n_actions)

        def context(index:int) -> Context:
            return rng.randoms(n_context_feats) if n_context_feats else None

        def actions(index:int, context: Context) -> Sequence[Action]:
            return  [rng.randoms(n_action_feats) for _ in range(n_actions)] if n_action_feats else A_ident

        def reward(index:int, context:Context, action:Action) -> float:

            W = weights
            X = context or [1]
            A = action
            F = X_encoder.encode(x=X,a=A)

            r = sum([w*f for w,f in zip(W,F)])
            e = (rng.random()-1/2)*math.sqrt(12)*math.sqrt(self._r_noise_var)
            
            return min(1,max(0,r+e))

        super().__init__(n_interactions, context, actions, reward)

    @property
    def params(self) -> Dict[str, Any]:
        """Paramaters describing the simulation."""

        return { 
            "n_A"    : self._n_actions,
            "n_C_phi": self._n_context_features,
            "n_A_phi": self._n_action_features,
            "r_noise": self._r_noise_var,
            "X"      : self._X,
            "seed"   : self._seed
        }

    def __str__(self) -> str:
        return f"LinearSynth(A={self._n_actions},c={self._n_context_features},a={self._n_action_features},X={self._X},seed={self._seed})"

class LocalSyntheticSimulation(LambdaSimulation):

    def __init__(self,
        n_interactions    : int = 500,
        n_contexts        : int = 200,
        n_context_features: int = 2,
        n_actions         : int = 10,
        seed:int = 1) -> None:

        self._n_interactions     = n_interactions
        self._n_context_features = n_context_features
        self._n_contexts         = n_contexts
        self._n_actions          = n_actions
        self._seed               = seed

        rng = CobaRandom(self._seed)

        contexts = [ tuple(rng.randoms(n_context_features)) for _ in range(self._n_contexts) ]        
        actions  = OneHotEncoder().fit_encode(range(n_actions))
        rewards  = {}

        for context in contexts:
            for action in actions:
                rewards[(context,action)] = rng.random()

        def context_generator(index:int):
            return rng.choice(contexts)

        def action_generator(index:int, context:Tuple[float,...]):
            return actions

        def reward_function(index:int, context:Tuple[float,...], action: Tuple[int,...]):
            return rewards[(context,action)]

        return super().__init__(self._n_interactions, context_generator, action_generator, reward_function)

    @property
    def params(self) -> Dict[str, Any]:
        """Paramaters describing the simulation."""

        return { 
            "n_A"    : self._n_actions,
            "n_C"    : self._n_contexts,
            "n_C_phi": self._n_context_features,
            "seed"   : self._seed
        }

    def __str__(self) -> str:
        return f"LocalSynth(A={self._n_actions},C={self._n_contexts},c={self._n_context_features},seed={self._seed})"
