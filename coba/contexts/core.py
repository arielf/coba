import sys
import json
import collections
import traceback

from pathlib import Path

from coba.typing import Iterable, Dict, Any, Sequence, Union, Literal
from coba.pipes import IO, NullIO
from coba.exceptions import CobaException
from coba.registry import CobaRegistry
from coba.utilities import coba_exit

from coba.contexts.cachers import Cacher
from coba.contexts.loggers import Logger

# To support class properties before python 3.9 we must implement our properties directly 
# on a meta class. Using class properties rather than class variables is done to allow 
# lazy loading. Lazy loading moves errors to execution time instead of import time where
# they are easier to debug as well as removing import time circular references.

# Creating a global configuration context to allow easy mocking and customization.
# In short, So long as the same modulename is always used to import and the import
# always occurs on the same thread I'm fairly confident this pattern will always work.
# In long, I'm somewhat unsure about this pattern for the following reasons:
#     > While there seems concensus that multi-import doesn't repeat (see [1]) it may if different modulenames are used (see [2])
#         [1] https://stackoverflow.com/a/19077396/1066291
#         [2] https://stackoverflow.com/q/13392038/1066291
#     > Python 3.7 added in explicit context management (see [3,4]) but this functionality is thread local only
#         [3] https://www.python.org/dev/peps/pep-0567/
#         [4] https://docs.python.org/3/library/contextvars.html

class CobaContext_meta(type):
    """To support class properties before python 3.9 we must implement our properties directly 
       on a meta class. Using class properties rather than class variables is done to allow 
       lazy loading. Lazy loading moves errors to execution time instead of import time where
       they are easier to debug as well as removing import time circular references.
    """

    class ExperimentConfig:
    
        def __init__(self, processes:int, maxtasksperchild:int, chunk_by: Literal["source","task"] = "source"):
            self.processes       : int                      = processes
            self.maxtasksperchild: int                      = maxtasksperchild
            self.chunk_by        : Literal["source","task"] = chunk_by

    def __init__(cls, *args, **kwargs):
        cls._api_keys     = None
        cls._cacher       = None
        cls._logger       = None
        cls._experiment   = None
        cls._search_paths = [Path.home() , Path.cwd(), Path(sys.path[0]) ]
        cls._store        = {}

    def _load_file_configs(cls) -> Dict[str,Any]:
        config = {}

        for search_path in cls.search_paths:

            potential_coba_config = search_path / ".coba"

            if potential_coba_config.exists() and potential_coba_config.read_text().strip() != "":
                try:
                    file_config = json.loads(potential_coba_config.read_text())

                    if not isinstance(file_config, dict):
                        raise CobaException(f"Expecting a JSON object (i.e., {{}}).")

                    cls._resolve_and_expand_paths(file_config, str(search_path))

                    config.update(file_config)
                
                except Exception as e:
                    raise CobaException(f"{str(e).strip('.')} in {potential_coba_config}.")

        return config

    def _resolve_and_expand_paths(cls, config_dict: dict, current_dir:str):
        for key,item in config_dict.items():
            if isinstance(item, dict):
                cls._resolve_and_expand_paths(item, current_dir)

            if isinstance(item,str) and item.strip().startswith("~"):
                config_dict[key] = str(Path(item).expanduser().resolve())

            if isinstance(item,str) and (item.strip().startswith("../") or item.strip().startswith("./")):
                config_dict[key] = str(Path(current_dir,item).resolve())

    _config_backing = None

    @property
    def _config(cls) -> Dict[str,Any]:

        if cls._config_backing is None:
            try:
                _raw_config: Dict[str,Any] = {
                    "api_keys"  : collections.defaultdict(lambda:None),
                    "cacher"    : { "DiskCacher": None},
                    "logger"    : { "IndentLogger": "Console" },
                    "experiment": { "processes": 1, "maxtasksperchild": 0, "chunk_by": "source" }
                }

                for key,value in cls._load_file_configs().items():
                    if key in _raw_config and isinstance(_raw_config[key],dict) and not CobaRegistry.is_known_recipe(value):
                        _raw_config[key].update(value)
                    else:
                        _raw_config[key] = value

                cls._config_backing = {
                    'api_keys'  : _raw_config['api_keys'],
                    'cacher'    : CobaRegistry.construct(_raw_config['cacher']),
                    'logger'    : CobaRegistry.construct(_raw_config['logger']),
                    'experiment': CobaContext_meta.ExperimentConfig(**_raw_config['experiment'])
                }
            except CobaException as e:
                messages = [
                    '',
                    "ERROR: An error occured while initializing CobaContext. Execution is unable to continue. Please see below for details:",
                    f"    > {e}",
                    ''
                ]
                coba_exit('\n'.join(messages))

            except Exception as e:
                messages = [
                    '',
                    "ERROR: An error occured while initializing CobaContext. Execution is unable to continue. Please see below for details:",
                    ''.join(traceback.format_tb(e.__traceback__)),
                    ''.join(traceback.TracebackException.from_exception(e).format_exception_only())
                ]
                coba_exit('\n'.join(messages))

        return cls._config_backing

    @property
    def api_keys(cls):
        cls._api_keys = cls._api_keys if cls._api_keys else cls._config['api_keys']
        return cls._api_keys

    @api_keys.setter
    def api_keys(cls, value):
        cls._api_keys = value

    @property
    def cacher(cls) -> Cacher[str,Iterable[bytes]]:
        cls._cacher = cls._cacher if cls._cacher else cls._config['cacher']
        return cls._cacher

    @cacher.setter
    def cacher(cls, value: Cacher) -> None:
        cls._cacher = value

    @property
    def logger(cls) -> Logger:
        cls._logger = cls._logger if cls._logger else cls._config['logger']
        return cls._logger

    @logger.setter
    def logger(cls, value: Logger) -> None:
        cls._logger = value

    @property
    def store(cls) -> Dict[str,Any]:
        return cls._store
    
    @store.setter
    def store(cls, value:Dict[str,Any]) -> None:
        cls._store = value

    @property
    def experiment(cls) -> 'CobaContext_meta.ExperimentConfig':
        cls._experiment = cls._experiment if cls._experiment else cls._config['experiment']
        return cls._experiment

    @property
    def search_paths(cls) -> Sequence[Path]:
        return cls._search_paths

    @search_paths.setter
    def search_paths(cls, value:Sequence[Union[str,Path]]) -> None:
        cls._search_paths = [ Path(path) if isinstance(path,str) else path for path in value  ]

class CobaContext(metaclass=CobaContext_meta):
    pass

class LearnerContext_meta(type):

    def __init__(cls, *args, **kwargs):
        cls._logger = None 

    @property
    def logger(cls) -> IO[Iterable[Dict[str,Any]],Dict[str,Any]]:
        return cls._logger if cls._logger is not None else NullIO[Dict[str,Any]]()

    @logger.setter
    def logger(cls, value: IO[Iterable[Dict[str,Any]],Dict[str,Any]]):
        cls._logger = value

class LearnerContext(metaclass=LearnerContext_meta):
    pass