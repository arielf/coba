import re
import collections
import collections.abc

from copy import copy
from pathlib import Path
from numbers import Number
from operator import truediv
from itertools import chain, repeat, accumulate
from typing_extensions import Literal
from typing import Any, Iterable, Dict, List, Tuple, Optional, Sequence, Hashable, Iterator, Union, Type, Set, Callable

from coba.config import CobaConfig
from coba.exceptions import CobaException
from coba.utilities import PackageChecker
from coba.pipes import JsonEncode, JsonDecode, DiskIO, MemoryIO, IO

class Table:
    """A container class for storing tabular data."""

    def __init__(self, name:str, primary_cols: Sequence[str], rows: Sequence[Dict[str,Any]], preferred_cols: Sequence[str] = []):
        """Instantiate a Table.

        Args:
            name: The name of the table. Used for display purposes.
            primary_cols: Table columns used to make each row's tuple "key".
            rows: The actual rows that should be stored in the table. Each row is required to contain the given primary_cols.
            preferred_cols: A list of columns that we prefer be displayed immediately after primary columns. All remaining 
                columns (i.e., neither primary nor preferred) will be ordered alphabetically.
        """
        self._name    = name
        self._primary = primary_cols

        for row in rows:
            assert len(row.keys() & primary_cols) == len(primary_cols), 'A Table row was provided without a primary key.'

        all_columns: Set[str] = set()
        for row in rows:
            all_columns |= {'index'} if '_packed' in row else set()
            all_columns |= row.keys()-{'_packed'}
            all_columns |= all_columns.union(row.get('_packed',{}).keys())

        col_priority = list(chain(primary_cols + ['index'] + preferred_cols + sorted(all_columns)))

        self._columns = sorted(all_columns, key=col_priority.index)
        self._rows_keys: List[Hashable               ] = []               
        self._rows_flat: Dict[Hashable, Dict[str,Any]] = {}
        self._rows_pack: Dict[Hashable, Dict[str,Any]] = {}

        for row in rows:
            row_key  = row[primary_cols[0]] if len(primary_cols) == 1 else tuple(row[col] for col in primary_cols)
            row_pack = row.pop('_packed',{})
            row_flat = row

            if row_pack:
                row_pack['index'] = list(range(1,len(list(row_pack.values())[0])+1))

            self._rows_keys.append(row_key)
            self._rows_pack[row_key] = row_pack
            self._rows_flat[row_key] = row_flat

        self._rows_keys = sorted(self._rows_keys)

    @property
    def name(self) -> str:
        return self._name

    @property
    def keys(self) -> Sequence[Hashable]:
        return self._rows_keys

    @property
    def columns(self) -> Sequence[str]:
        return self._columns

    @property
    def dtypes(self) -> Sequence[Type[Union[int,float,bool,object]]]:

        flats = self._rows_flat
        packs = self._rows_pack

        columns_packed = [ any([ col in packs[key] for key in self.keys]) for col in self.columns ]
        columns_values = [ [flats[key].get(col, packs[key].get(col, self._default(col))) for key in self.keys] for col in self.columns ]

        return [ self._infer_type(column_packed, column_values) for column_packed, column_values in zip(columns_packed,columns_values)]

    def filter(self, row_pred:Callable[[Dict[str,Any]],bool] = None, **kwargs) -> 'Table':

        def satisifies_filter(col_filter,col_value):
            if col_filter == col_value:
                return True

            if isinstance(col_filter,Number) and isinstance(col_value,str):
                return re.search(f'(\D|^){col_filter}(\D|$)', col_value)

            if isinstance(col_filter,str) and isinstance(col_value,str):
                return re.search(col_filter, col_value)

            if callable(col_filter):
                return col_filter(col_value)

            return False

        def satisfies_all_filters(key):
            row = self[key]

            row_filter_results = [ row_pred is None or row_pred(row) ]
            col_filter_results = [ ]

            for col,col_filter in kwargs.items():

                if isinstance(col_filter,collections.abc.Container) and not isinstance(col_filter,str):

                    col_filter_results.append(row[col] in col_filter or any([satisifies_filter(cf,row[col]) for cf in col_filter]))

                else:
                    col_filter_results.append(satisifies_filter(col_filter,row.get(col,self._default(col)) ))

            return all(row_filter_results+col_filter_results)

        new_result = copy(self)
        new_result._rows_keys = list(filter(satisfies_all_filters,self.keys))

        return new_result

    def to_pandas(self) -> Any:
        PackageChecker.pandas("Table.to_pandas")
        import pandas as pd #type: ignore
        import numpy as np  #type: ignore #pandas installs numpy so if we have pandas we have numpy

        col_numpy = { col: np.empty(len(self), dtype=dtype) for col,dtype in zip(self.columns,self.dtypes)}

        row_index = 0

        for key in self.keys:

            flat = self._rows_flat[key]
            pack = self._rows_pack[key]

            pack_size = 1 if not pack else len(pack['index'])

            for col in self.columns:
                if col in pack:
                    val = pack[col]

                elif col in flat:
                    if isinstance(flat[col], (tuple,list)):
                        val = [flat[col]]
                    else:
                        val = flat[col]

                else:
                    val = self._default(col)
                    
                col_numpy[col][row_index:(row_index+pack_size)] = val

            row_index += pack_size

        return pd.DataFrame(col_numpy, columns=self.columns)

    def to_tuples(self) -> Sequence[Tuple[Any,...]]:

        tooples = []

        for key in self.keys:
            
            flat = self._rows_flat[key]
            pack = self._rows_pack[key]

            if not pack:
                tooples.append(tuple(flat.get(col,self._default(col)) for col in self.columns))
            else:
                tooples.extend(list(zip(*[pack.get(col,repeat(flat.get(col,self._default(col)))) for col in self.columns])))

        return tooples

    def _default(self, column:str) -> Any:
        return [1] if column == "index" else None

    def _infer_type(self, is_packed: bool, values: Sequence[Any]) -> Type[Union[int,float,bool,object]]:

        types: List[Optional[Type[Any]]] = []

        to_type = lambda value: None if value is None else type(value)

        for value in values:
            if is_packed and isinstance(value, (list,tuple)):
                types.extend([to_type(v) for v in value])
            else:
                types.append(to_type(value))
        
        return self._resolve_types(types)

    def _resolve_types(self, types: Sequence[Optional[Type[Any]]]) -> Type[Union[int,float,bool,object]]:
        types = list(set(types))

        if len(types) == 1 and types[0] in [dict,str]:
            return object
        
        if len(types) == 1 and types[0] in [int,float,bool]:
            return types[0]

        if all(t in [None,int,float] for t in types):
            return float

        return object

    def __iter__(self) -> Iterator[Dict[str,Any]]:
        for key in self.keys:
            yield self[key]

    def __contains__(self, key: Union[Hashable, Sequence[Hashable]]) -> bool:
        return key in self.keys

    def __str__(self) -> str:
        return str({"Table": self.name, "Columns": self.columns, "Rows": len(self)})

    def _ipython_display_(self):
        #pretty print in jupyter notebook (https://ipython.readthedocs.io/en/stable/config/integrating.html)
        print(str(self))

    def __len__(self) -> int:
        return sum([ len(self._rows_pack[key].get('index',[None])) for key in self.keys ])

    def __getitem__(self, key: Union[Hashable, Sequence[Hashable]]) -> Dict[str,Any]:
        if key not in self.keys: raise KeyError(key)
        return dict(**self._rows_flat[key], **self._rows_pack[key])

class InteractionsTable(Table):

    def to_progressive_lists(self, span: int = None, each: bool = False, yaxis: str = "reward"):
        #Learner, Simulation, Index
        #Learner,             Index

        lrn_sim_rows = []

        for interactions in self:

            rewards = interactions[yaxis]

            if span is None or span >= len(rewards):
                cumwindow  = list(accumulate(rewards))
                cumdivisor = list(range(1,len(cumwindow)+1))

            elif span == 1:
                cumwindow  = list(rewards)
                cumdivisor = [1]*len(cumwindow)

            else:
                alpha = 2/(1+span)
                cumwindow  = list(accumulate(rewards          , lambda a,c: c + (1-alpha)*a))
                cumdivisor = list(accumulate([1.]*len(rewards), lambda a,c: c + (1-alpha)*a)) #type: ignore

            lrn_sim_rows.append([interactions["learner_id"], interactions["environment_id"], *list(map(truediv, cumwindow, cumdivisor))])

        if each:
            return lrn_sim_rows

        else:
            grouped_lrn_sim_rows = collections.defaultdict(list)

            for row in lrn_sim_rows:
                grouped_lrn_sim_rows[row[0]].append(row[2:])

            lrn_rows = []

            for learner_id in grouped_lrn_sim_rows.keys():

                Z = list(zip(*grouped_lrn_sim_rows[learner_id]))

                if not Z: continue

                Y = [ sum(z)/len(z) for z in Z ]

                lrn_rows.append([learner_id, *Y])

            return lrn_rows

    def to_progressive_pandas(self, span: int = None, each: bool = False, yaxis: str = "reward"):
        PackageChecker.pandas("Result.to_pandas")

        import pandas as pd

        data = self.to_progressive_lists(span, each, yaxis)
        
        if each:
            n_index = len(data[0][2:])
            return pd.DataFrame(data, columns=["learner_id", "environment_id", *range(1,n_index+1)])
        
        else:
            n_index = len(data[0][1:])
            return pd.DataFrame(data, columns=["learner_id", *range(1,n_index+1)])

class TransactionIO_V3(IO[Iterable[Any], Any]):

    def __init__(self, transaction_log: Optional[str] = None, minify:bool=True) -> None:

        self._io = DiskIO(transaction_log) if transaction_log else MemoryIO()
        self._minify = minify

    def write(self, item: Any) -> None:

        item = self._encode(item)

        if isinstance(self._io, MemoryIO):
            self._io.write(item)
        else:
            self._io.write(JsonEncode(self._minify).filter(item))

    def read(self) -> Iterable[Any]:
        if isinstance(self._io, MemoryIO):
            return self._io.read()
        else:
            return map(JsonDecode().filter,self._io.read())

    @property
    def result(self) -> 'Result':
        
        n_lrns   = None
        n_sims   = None
        lrn_rows = {}
        sim_rows = {}
        int_rows = {}

        for trx in self.read():

            if trx[0] == "benchmark": 
                n_lrns = trx[1]["n_learners"]
                n_sims = trx[1]["n_simulations"]
            
            if trx[0] == "S": 
                sim_rows[trx[1]] = trx[2]
            
            if trx[0] == "L": 
                lrn_rows[trx[1]] = trx[2]
            
            if trx[0] == "I": 
                int_rows[tuple(trx[1])] = trx[2]

        return Result(n_lrns, n_sims, sim_rows, lrn_rows, int_rows)

    def _encode(self,item):
        if item[0] == "T0":
            return ['benchmark', {"n_learners":item[1], "n_simulations":item[2]}]

        if item[0] == "T1":
            return ["L", item[1], item[2]]

        if item[0] == "T2":
            return ["S", item[1], item[2]]

        if item[0] == "T3":
            rows_T = collections.defaultdict(list)

            for row in item[2]:
                for col,val in row.items():
                    if col == "rewards" : col="reward"
                    if col == "reveals" : col="reveal"
                    rows_T[col].append(val)

            return ["I", item[1], { "_packed": rows_T }]

class TransactionIO_V4(IO[Iterable[Any], Any]):

    def __init__(self, transaction_log: Optional[str] = None, minify:bool=True) -> None:
        self._io     = DiskIO(transaction_log) if transaction_log else MemoryIO()
        self._minify = minify

    def write(self, item: Any) -> None:
        if isinstance(self._io, MemoryIO):
            self._io.write(self._encode(item))
        else:
            self._io.write(JsonEncode(self._minify).filter(self._encode(item)))

    def read(self) -> Iterable[Any]:
        if isinstance(self._io, MemoryIO):
            return self._io.read()
        else:
            return map(JsonDecode().filter,self._io.read())

    @property
    def result(self) -> 'Result':
        
        n_lrns   = None
        n_sims   = None
        lrn_rows = {}
        env_rows = {}
        int_rows = {}

        for trx in self.read():

            if trx[0] == "experiment": 
                n_lrns = trx[1]["n_learners"]
                n_sims = trx[1]["n_environments"]
            
            if trx[0] == "E": 
                env_rows[trx[1]] = trx[2]
            
            if trx[0] == "L": 
                lrn_rows[trx[1]] = trx[2]
            
            if trx[0] == "I": 
                int_rows[tuple(trx[1])] = trx[2]

        return Result(n_lrns, n_sims, env_rows, lrn_rows, int_rows)

    def _encode(self,item):
        if item[0] == "T0":
            return ['experiment', {"n_learners":item[1], "n_environments":item[2]}]

        if item[0] == "T1":
            return ["L", item[1], item[2]]

        if item[0] == "T2":
            return ["E", item[1], item[2]]

        if item[0] == "T3":
            rows_T = collections.defaultdict(list)

            for row in item[2]:
                for col,val in row.items():
                    if col == "rewards" : col="reward"
                    if col == "reveals" : col="reveal"
                    rows_T[col].append(val)

            return ["I", item[1], { "_packed": rows_T }]

        return item

class TransactionIO(IO[Iterable[Any], Any]):

    def __init__(self, transaction_log: Optional[str] = None) -> None:

        if not transaction_log or not Path(transaction_log).exists():
            version = None
        else:
            version = JsonDecode().filter(next(DiskIO(transaction_log).read()))[1]

        if version == 3:
            self._transactionIO = TransactionIO_V3(transaction_log)

        elif version == 4:
            self._transactionIO = TransactionIO_V4(transaction_log)

        elif version is None:
            self._transactionIO = TransactionIO_V4(transaction_log)
            self._transactionIO.write(['version',4])

        else:
            raise CobaException("We were unable to determine the appropriate Transaction reader for the file.")

    def write(self, transaction: Any) -> None:
        self._transactionIO.write(transaction)

    def read(self) -> Iterable[Any]:
        self._transactionIO.read()

    @property
    def result(self) -> 'Result':
        return self._transactionIO.result

    def _encode(self,item):
        if item[0] == "T0":
            return ['benchmark', {"n_learners":item[1], "n_simulations":item[2]}]

        if item[0] == "T1":
            return ["L", item[1], item[2]]

        if item[0] == "T2":
            return ["S", item[1], item[2]]

        if item[0] == "T3":
            rows_T = collections.defaultdict(list)

            for row in item[2]:
                for col,val in row.items():
                    if col == "rewards" : col="reward"
                    if col == "reveals" : col="reveal"
                    rows_T[col].append(val)

            return ["I", item[1], { "_packed": rows_T }]

class Result:
    """A class representing the result of an Experiment."""

    @staticmethod
    def from_file(filename: str) -> 'Result':
        """Create a Result from a transaction file."""
        
        if not Path(filename).exists(): 
            raise CobaException("We were unable to find the given Result file.")

        return TransactionIO(filename).result

    def __init__(self,
        n_lrns  : int = None,
        n_envs  : int = None,
        env_rows: Dict[int           ,Dict[str,Any]] = {},
        lrn_rows: Dict[int           ,Dict[str,Any]] = {},
        int_rows: Dict[Tuple[int,int],Dict[str,Any]] = {}) -> None:
        """Instantiate a Result class."""

        self.experiment = {}

        if n_lrns is not None: self.experiment["n_learners"] = n_lrns
        if n_envs is not None: self.experiment["n_environments"] = n_envs

        env_flat = [ { "environment_id":k,                       **v } for k,v in env_rows.items() ]
        lrn_flat = [ {                        "learner_id" :k,   **v } for k,v in lrn_rows.items() ]
        int_flat = [ { "environment_id":k[0], "learner_id":k[1], **v } for k,v in int_rows.items() ]

        self._environments = Table            ("Environments", ['environment_id'              ], env_flat, ["source"])
        self._learners     = Table            ("Learners"    , ['learner_id'                  ], lrn_flat, ["family","shuffle","take"])
        self._interactions = InteractionsTable("Interactions", ['environment_id', 'learner_id'], int_flat, ["index","reward"])

    @property
    def learners(self) -> Table:
        """The collection of learners evaluated by Experiment. The easiest way to work with the 
            learners is to convert them to a pandas data frame via Result.learners.to_pandas()
        """
        return self._learners

    @property
    def environments(self) -> Table:
        """The collection of environments used to evaluate each learner in the Experiment. The easiest
            way to work with environments is to convert to a dataframe via Result.environments.to_pandas()
        """
        return self._environments

    @property
    def interactions(self) -> InteractionsTable:
        """The collection of interactions that learners chose actions for in the Experiment. Each interaction
            has a environment_id and learner_id column to link them to the learners and environments tables. The 
            easiest way to work with interactions is to convert to a dataframe via Result.interactions.to_pandas()
        """
        return self._interactions

    def copy(self) -> 'Result':
        result = Result()

        result.environments = copy(self._environments)
        result.learners     = copy(self._learners)
        result.interactions = copy(self._interactions)

        return result

    def filter_fin(self) -> 'Result':

        def is_complete_sim(sim_id):
            return all((sim_id, lrn_id) in self.interactions for lrn_id in self.learners.keys)

        new_result               = copy(self)
        new_result._environments = self.environments.filter(environment_id=is_complete_sim)
        new_result._interactions = self.interactions.filter(environment_id=is_complete_sim)

        if len(new_result.environments) == 0:
            CobaConfig.logger.log(f"No simulation was found with interaction data for every learner.")

        return new_result

    def filter_env(self, pred:Callable[[Dict[str,Any]],bool] = None, **kwargs) -> 'Result':

        new_result = copy(self)
        new_result._environments = new_result.environments.filter(pred, **kwargs)
        new_result._interactions = new_result.interactions.filter(environment_id=new_result.environments)

        if len(new_result.environments) == 0:
            CobaConfig.logger.log(f"No environments matched the given filter: {kwargs}.")

        return new_result

    def filter_lrn(self, pred:Callable[[Dict[str,Any]],bool] = None, **kwargs) -> 'Result':
        new_result = copy(self)
        new_result._learners     = new_result.learners.filter(pred, **kwargs)
        new_result._interactions = new_result.interactions.filter(learner_id=new_result.learners)

        if len(new_result.learners) == 0:
            CobaConfig.logger.log(f"No learners matched the given filter: {kwargs}.")

        return new_result

    def plot_learners(self, 
        xlim : Optional[Tuple[Number,Number]] = None,
        ylim : Optional[Tuple[Number,Number]] = None,
        span : int = None,
        err  : Optional[Literal['se','sd']] = None,
        each : bool = False,
        filename: str = None,
        ax = None) -> None:
        """This plots the performance of multiple learners on multiple environments. It gives a sense of the expected 
            performance for different learners across independent environments. This plot is valuable in gaining insight 
            into how various learners perform in comparison to one another. 

        Args:
            xlim: Define the x-axis limits to plot. If `None` the x-axis limits will be inferred.
            ylim: Define the y-axis limits to plot. If `None` the y-axis limits will be inferred.
            span: In general this indicates how many previous evaluations to average together. In practice this works
                identically to ewm span value in the Pandas API. Additionally, if span equals None then all previous 
                rewards are averaged together vs span = 1 WHERE the instantaneous reward is plotted for each interaction.
            err: Determine what kind of error bars to plot (if any). Valid types are `None`, 'se', and 'sd'. If `None`
                then no bars are plotted, if 'se' the standard error is shown, and if 'sd' the standard deviation is shown.
            each: Determine whether each constituent observation used to estimate mean performance is also plotted.
            filename: Provide a filename to write plot image to disk.
            ax: Provide an optional axes that the plot will be drawn to. If not provided a new figure/axes is created.
        """

        PackageChecker.matplotlib('Result.plot_learners')
        import matplotlib.pyplot as plt #type: ignore
        import numpy as np              #type: ignore

        progressives: Dict[int,List[Sequence[float]]] = collections.defaultdict(list)

        for progressive in self.interactions.to_progressive_lists(span=span,each=True):
            progressives[progressive[0]].append(progressive[2:])

        if not progressives:
            return
        
        show = ax is None

        if ax is None:
            ax  = plt.figure(figsize=(10,6)).add_subplot(111) #type: ignore

        for learner_id in sorted(self.learners.keys, key=lambda id: self.learners[id]["full_name"]):

            color = next(ax._get_lines.prop_cycler)['color']

            label = self._learners[learner_id]["full_name"]
            Z     = list(zip(*progressives[learner_id]))
            
            if not Z: continue

            N     = [ len(z) for z in Z        ]
            Y     = [ sum(z)/len(z) for z in Z ]
            X     = list(range(1,len(Y)+1))

            start = xlim[0] if xlim else int(.05*len(X))
            end   = xlim[1] if xlim else len(X)

            if start >= end:
                CobaConfig.logger.log("The plot's end is less than the start making plotting impossible.")
                return

            X = X[start:end]
            Y = Y[start:end]
            Z = Z[start:end]

            if len(X) == 0: continue

            #this is much faster than python's native stdev
            #and more or less free computationally so we always
            #calculate it regardless of if they are showing them
            #we are using the identity Var[Y] = E[Y^2]-E[Y]^2
            Y2 = [ sum([zz**2 for zz in z])/len(z) for z in Z            ]
            SD = [ (round(y2-y**2,8))**(1/2)       for y,y2 in zip(Y,Y2) ]
            SE = [ sd/(n**(1/2))                   for sd,n in zip(SD,N) ]

            yerr = 0 if err is None else SE if err.lower() == 'se' else SD if err.lower() == 'sd' else 0
            ax.errorbar(X, Y, yerr=yerr, elinewidth=0.5, errorevery=(0,max(int(len(X)*0.05),1)), label=label, color=color)

            if each:
                for Y in list(zip(*Z)):
                    ax.plot(X,Y, color=color, alpha=0.15)

        padding = .05
        ax.margins(0)
        ax.set_xticks(np.clip(ax.get_xticks(), *ax.get_xlim()))
        ax.margins(padding)

        if xlim:
            x_pad = padding*(xlim[1]-xlim[0])
            ax.set_xlim(xlim[0]-x_pad, xlim[1]+x_pad)

        if ylim:
            y_pad = padding*(ylim[1]-ylim[0])
            ax.set_ylim(ylim[0]-y_pad, ylim[1]+y_pad)

        ax.set_title(("Instantaneous" if span == 1 else "Progressive" if span is None else f"Span {span}") + " Reward", loc='left',pad=15)
        ax.set_ylabel("Reward")
        ax.set_xlabel("Interactions")

        if ax.get_legend() is None:
            scale = 0.65
            box1 = ax.get_position()
            ax.set_position([box1.x0, box1.y0 + box1.height * (1-scale), box1.width, box1.height * scale])
        else:
            ax.get_legend().remove()

        ax.legend(*ax.get_legend_handles_labels(), loc='upper left', bbox_to_anchor=(-.01, -.25), ncol=1, fontsize='medium') #type: ignore

        if show:
            plt.show()

        if filename:
            plt.savefig(filename, dpi=300)

    def __str__(self) -> str:
        return str({ "Learners": len(self._learners), "Environments": len(self._environments), "Interactions": len(self._interactions) })

    def _ipython_display_(self):
        #pretty print in jupyter notebook (https://ipython.readthedocs.io/en/stable/config/integrating.html)
        print(str(self))
