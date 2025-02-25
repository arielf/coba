import collections.abc

from itertools import chain, repeat
from typing import Any, Iterable, Union, Sequence, overload, Dict, MutableSequence, MutableMapping, Tuple, Optional
from coba.backports import Literal

from coba.encodings import OneHotEncoder
from coba.random import CobaRandom
from coba.pipes import Pipes, Source, ListSource, Structure, Reservoir, UrlSource, CsvReader
from coba.pipes import CsvReader, ArffReader, LibsvmReader, ManikReader
from coba.statistics import percentile

from coba.environments.simulated.primitives import SimulatedEnvironment, SimulatedInteraction

class CsvSource(Source[Iterable[MutableSequence]]):
    """Load a source (either local or remote) in CSV format.

    This is primarily used by SupervisedSimulation to create Environments for Experiments.
    """

    def __init__(self, source: Union[str,Source[Iterable[str]]], has_header:bool=False, **dialect) -> None:
        """Instantiate a CsvSource.

        Args:
            source: The data source. Accepts either a string representing the source location or another Source.
            has_header: Indicates if the CSV files has a header row. 
        """
        source = UrlSource(source) if isinstance(source,str) else source
        reader = CsvReader(has_header, **dialect)
        self._source = Pipes.join(source, reader)

    def read(self) -> Iterable[MutableSequence]:
        """Read and parse the csv source."""
        return self._source.read()

    @property
    def params(self) -> Dict[str, Any]:
        """Parameters describing the csv source."""
        return self._source.params

    def __str__(self) -> str:
        return str(self._source)

class ArffSource(Source[Union[Iterable[MutableSequence], Iterable[MutableMapping]]]):
    """Load a source (either local or remote) in ARFF format.

    This is primarily used by SupervisedSimulation to create Environments for Experiments.
    """

    def __init__(self, 
        source: Union[str,Source[Iterable[str]]],
        cat_as_str: bool = False,
        skip_encoding: bool = False,
        lazy_encoding: bool = True,
        header_indexing: bool = True) -> None:
        """Instantiate an ArffSource.

        Args:
            source: The data source. Accepts either a string representing the source location or another Source.
            cat_as_str: Indicates that categorical features should be encoded as a string rather than one hot encoded. 
            skip_encoding: Indicates that features should not be encoded (this means all features will be strings).
            lazy_encoding: Indicates that features should be encoded lazily (this can save time if rows will be dropped).
            header_indexing: Indicates that header data should be preserved so rows can be indexed by header name. 
        """
        source = UrlSource(source) if isinstance(source,str) else source
        reader = ArffReader(cat_as_str, skip_encoding, lazy_encoding, header_indexing)
        self._source = Pipes.join(source, reader)

    def read(self) -> Union[Iterable[MutableSequence], Iterable[MutableMapping]]:
        """Read and parse the arff source."""
        return self._source.read()

    @property
    def params(self) -> Dict[str, Any]:
        """Parameters describing the arff source."""
        return self._source.params

    def __str__(self) -> str:
        return str(self._source)

class LibSvmSource(Source[Iterable[MutableMapping]]):
    """Load a source (either local or remote) in libsvm format.

    This is primarily used by SupervisedSimulation to create Environments for Experiments.
    """

    def __init__(self, source: Union[str,Source[Iterable[str]]]) -> None:
        """Instantiate a LibsvmSource.

        Args:
            source: The data source. Accepts either a string representing the source location or another Source.
        """
        source = UrlSource(source) if isinstance(source,str) else source
        reader = LibsvmReader()
        self._source = Pipes.join(source, reader)

    def read(self) -> Iterable[MutableMapping]:
        """Read and parse the libsvm source."""
        return self._source.read()

    @property
    def params(self) -> Dict[str, Any]:
        """Parameters describing the libsvm source."""
        return self._source.params

    def __str__(self) -> str:
        return str(self._source)

class ManikSource(Source[Iterable[MutableMapping]]):
    """Load a source (either local or remote) in Manik format.

    This is primarily used by SupervisedSimulation to create Environments for Experiments.
    """

    def __init__(self, source: Union[str,Source[Iterable[str]]]) -> None:
        """Instantiate a ManikSource.

        Args:
            source: The data source. Accepts either a string representing the source location or another Source.
        """
        source = UrlSource(source) if isinstance(source,str) else source
        reader = ManikReader()
        self._source = Pipes.join(source, reader)

    def read(self) -> Iterable[MutableMapping]:
        """Read and parse the manik source."""
        return self._source.read()

    @property
    def params(self) -> Dict[str, Any]:
        """Parameters describing the manik source."""
        return self._source.params

    def __str__(self) -> str:
        return str(self._source)

class SupervisedSimulation(SimulatedEnvironment):
    """Create a contextual bandit simulation using an existing supervised regression or classification dataset."""

    @overload
    def __init__(self,
        source: Source = None,
        label_col: Union[int,str] = None,
        label_type: Literal["C","R"] = "C",
        take: Union[int, Tuple[Optional[int], Optional[int]]] = None) -> None:
        """Instantiate a SupervisedSimulation.

        Args:
            source: A source object that reads the supervised data.
            label_col: The header name or index which identifies the label feature in each example. If
                label_col is None the source must return an iterable of tuple pairs where the first item
                are the features and the second item is the label.
            label_type: Indicates whether the label column is a classification or regression value.
            take: The number of random examples you'd like to draw from the given data set for the environment.
        """
        ...

    @overload
    def __init__(self,
        X: Sequence[Any],
        Y: Sequence[Any],
        label_type: Literal["C","R"] = "C") -> None:
        """Instantiate a SupervisedSimulation.

        Args:
            X: A sequence of example features that will be used to create interaction contexts in the simulation.
            Y: A sequence of supervised labels that will be used to construct actions and rewards in the simulation.
            label_type: Indicates whether the label column is a classification or regression value.
        """
        ...

    def __init__(self, *args, **kwargs) -> None:
        """Instantiate a SupervisedSimulation."""

        if 'source' in kwargs or (args and hasattr(args[0], 'read')):
            source     = args[0] if len(args) > 0 else kwargs['source']
            label_col  = args[1] if len(args) > 1 else kwargs.get("label_col", None)
            label_type = args[2] if len(args) > 2 else kwargs.get("label_type", "C")
            take       = args[3] if len(args) > 3 else kwargs.get("take", None)
            if take      is not None: source = Pipes.join(source, Reservoir(take))
            if label_col is not None: source = Pipes.join(source, Structure((None,label_col)))
            params = source.params

        else:
            X          = args[0]
            Y          = args[1]
            label_type = args[2] if len(args) > 2 else kwargs.get("label_type", "C")
            source     = ListSource(list(zip(X,Y)))
            params     = {"source": "[X,Y]"}

        self._label_type = label_type
        self._source     = source
        self._params     = {**params, "label_type": self._label_type, "type": "SupervisedSimulation" }

    @property
    def params(self) -> Dict[str,Any]:
        return self._params

    def read(self) -> Iterable[SimulatedInteraction]:

        items = list(self._source.read())

        if not items: return []

        features,labels = zip(*items)

        if self._label_type == "R":
            max_n_actions = 10

            #Scale the labels so their range is 1.
            min_l, max_l = min(labels), max(labels)
            labels = [float(l)/(max_l-min_l)-(min_l/(max_l-min_l)) for l in labels]

            if len(labels) <= max_n_actions:
                actions = labels
            else:
                actions = percentile(labels, [i/(max_n_actions+1) for i in range(1,max_n_actions+1)])

            values  = dict(zip(OneHotEncoder().fit_encodes(actions), actions))
            actions = list(values.keys())

            reward = lambda action,label: 1-abs(values[action]-float(label))
        else:
            #how can we tell the difference between featurized labels and multilabels????
            #for now we will assume multilables will be passed in as arrays not tuples...
            if not isinstance(labels[0], collections.abc.Hashable):
                actions = list(chain.from_iterable(labels))
            else:
                actions = list(labels)

            is_label      = lambda action,label: action == label
            in_multilabel = lambda action,label: isinstance(label,collections.abc.Sequence) and action in label
            reward        = lambda action,label: int(is_label(action,label) or in_multilabel(action,label))

        contexts = features
        actions  = CobaRandom(1).shuffle(sorted(set(actions)))
        rewards  = [ [ reward(action,label) for action in actions ] for label in labels ]

        for c,a,r in zip(contexts, repeat(actions), rewards):
            yield SimulatedInteraction(c,a,rewards=r)
