"""The contexts module contains classes determining the context for shared functionality.

TODO Add unittests for CobaConfig.
"""

import json
import copy
import collections
import time

from contextlib import contextmanager
from itertools import repeat
from gzip import compress, decompress
from abc import ABC, abstractmethod
from io import BytesIO
from pathlib import Path
from datetime import datetime
from typing import (
    Callable, ContextManager, Union, Generic, TypeVar, Dict, 
    IO, Mapping, Any, Optional, List, MutableMapping, cast, Iterator
)

_K = TypeVar("_K")
_V = TypeVar("_V")

class TemplatingEngine():
    """This class materializes templates within benchmark json files.
    
    The templating engine works as follows: 
        1. Look in the root object for a "templates" object. Templates should be be objects themselves
        with hard coded values and variables. Variable values are indicated by beginning with a $.
        2. Recursively walk through the remainder of the children from the root. For every object found
        check to see if it has a "template" value. 
        3. For every object found with a "template" value defined materialize all of that template's static
        values into this object. If an object has a static variable defined that is also in the template give
        preference to the local object's value.
        4. Assign any defined variables to the template as well (i.e., those values that start with a $). 
        5. Keep defined variables in context while walking child objects in case they are needed as well.
    """
    
    @staticmethod
    def parse(json_val:Union[str, Dict[str,Any]]):

        root = json.loads(json_val) if isinstance(json_val, str) else json_val

        if "templates" in root:

            templates: Dict[str,Dict[str,Any]] = root.pop("templates")
            nodes    : List[Any]               = [root]
            scopes   : List[Dict[str,Any]]     = [{}]

            def materialize_template(document: MutableMapping[str,Any], template: Mapping[str,Any]):

                for key in template:
                    if key in document:
                        if isinstance(template[key], collections.Mapping) and isinstance(template[key], collections.Mapping):
                            materialize_template(document[key],template[key])
                    else:
                        document[key] = template[key]

            def materialize_variables(document: MutableMapping[str,Any], variables: Mapping[str,Any]):
                for key in document:
                    if isinstance(document[key],str) and document[key] in variables:
                        document[key] = variables[document[key]]

            while len(nodes) > 0:
                node  = nodes.pop()
                scope = scopes.pop().copy()  #this could absolutely be made more memory-efficient if needed

                if isinstance(node, collections.MutableMapping):

                    if "template" in node and node["template"] not in templates:
                        raise Exception(f"We were unable to find template '{node['template']}'.")

                    keys      = list(node.keys())
                    template  = templates[node.pop("template")] if "template" in node else cast(Dict[str,Any], {})
                    variables = { key:node.pop(key) for key in keys if key.startswith("$") }

                    template = copy.deepcopy(template)
                    scope.update(variables)

                    materialize_template(node, template)
                    materialize_variables(node, scope)

                    for child_node, child_scope in zip(node.values(), repeat(scope)):
                        nodes.append(child_node)
                        scopes.append(child_scope)

                if isinstance(node, collections.Sequence) and not isinstance(node, str):
                    for child_node, child_scope in zip(node, repeat(scope)):
                        nodes.append(child_node)
                        scopes.append(child_scope)

        return root

class CobaConfig():
    """A helper class to find and load coba config files.""" 

    def __init__(self):
        """Instantiate a CobaConfig class."""
        
        search_paths = [Path("./.coba"), Path.home() / ".coba"]

        config = {}

        for potential_path in search_paths:
            if potential_path.exists():
                with open(potential_path) as fs:
                    config = json.load(fs)
                break

        self._config = config

    @property
    def openml_api_key(self) -> Optional[str]:
        return self._config.get("openml_api_key", None)

    @property
    def file_cache(self) -> Mapping[str,Any]:
        return self._config.get("file_cache", {"type":"none"})        

class CacheInterface(Generic[_K, _V], ABC):
    """The interface for a cacher."""
    
    @abstractmethod
    def __contains__(self, key: _K) -> bool:
        ...

    @abstractmethod
    def get(self, key: _K) -> _V:
        ...

    @abstractmethod
    def put(self, key: _K, value: _V) -> _V:
        ...

    @abstractmethod
    def rmv(self, key: _K) -> None:
        ...

class NoneCache(CacheInterface[_K, _V]):
    def __init__(self) -> None:
        self._cache: Dict[_K,_V] = {}

    def __contains__(self, key: _K) -> bool:
        return False

    def get(self, key: _K) -> _V:
        raise Exception("the key didn't exist in the cache")

    def put(self, key: _K, value: _V) -> _V:
        return value

    def rmv(self, key: _K):
        pass

class MemoryCache(CacheInterface[_K, _V]):
    def __init__(self) -> None:
        self._cache: Dict[_K,_V] = {}

    def __contains__(self, key: _K) -> bool:
        return key in self._cache

    def get(self, key: _K) -> _V:
        return self._cache[key]

    def put(self, key: _K, value: _V) -> _V:
        self._cache[key] = value

        return value

    def rmv(self, key: _K):
        del self._cache[key]

class DiskCache(CacheInterface[str, IO[bytes]]):
    """A cache that writes to disk.
    
    Internally the DiskCache compresses all given bytes before storing them to disk
    in order to conserve space. If one wishes to pass in compressed bytes or wishes
    wishes to get compressed bytes from the cache they can indicate this by appending 
    .gz to the end of the given filename.
    """

    def __init__(self, path: Union[str, Path]) -> None:
        """Instantiate a DiskCache.
        
        Args:
            path: The path to the directory where all files will be cached
        """
        self._cache_dir = path if isinstance(path, Path) else Path(path).expanduser()
        self._cache_dir.parent.mkdir(parents=True, exist_ok=True)

    def __contains__(self, filename: str) -> bool:
        return self._private_path(filename).exists()

    def get(self, filename: str) -> IO[bytes]:
        """Get a filename from the cache.
        
        If the requested filename has a .gz suffix the returned bytes will be compressed. If
        the requested filename does not end with .gz the returned bytes will not be compressed.

        Args:
            filename: Requested filename to retreive from the cache.
        """

        requested_gz   = filename.endswith(".gz")
        resource_path  = self._private_path(filename)
        resource_bytes = resource_path.read_bytes()
        response_bytes = resource_bytes if requested_gz else decompress(resource_bytes)

        return BytesIO(response_bytes)

    def put(self, filename: str, value: IO[bytes]) -> IO[bytes]:
        """Put a filename and its bytes into the cache.
        
        If the given filename has a .gz suffix the given bytes are assumed to be compressed. If
        the given filename does not end with .gz the given bytes are assumed to not be compressed.

        Args:
            filename: The filename to store in the cache.
            value: The bytes that should be cached for the given filename.
        """


        received_gz = filename.endswith(".gz")
        resource_path = self._private_path(filename)

        received_bytes = value.read()
        resource_bytes = received_bytes if received_gz else compress(received_bytes)

        resource_path.touch()
        resource_path.write_bytes(resource_bytes)

        return BytesIO(received_bytes)

    def rmv(self, filename: str) -> None:
        """Remove a filename from the cache.

        Args:
            filename: The filename to remove from the cache.
        """

        resource_path = self._private_path(filename)
        if resource_path.exists(): resource_path.unlink()

    def _private_name(self, filename: str) -> str:
        return filename if filename.endswith(".gz") else (filename + ".gz")

    def _private_path(self, filename: str) -> Path:
        return self._cache_dir/self._private_name(filename)

class LoggerInterface(ABC):
    """The interface for a Logger"""
    
    @abstractmethod
    def log(self, message: str, end:str = None) -> 'ContextManager[LoggerInterface]':
        ...

    @abstractmethod
    def log_exception(self, exception:Exception, preamble: str = '') -> None:
        ...

class UniversalLogger(LoggerInterface):
    """A simple implementation of the LoggerInterface.
    
    This logger allows for its print_function to be overriden. This logger also supports
    logging levels via a context returned with the log command. All logs that occur within
    that context will be indented and written as sublists.

    """

    def __init__(self, print_function: Callable[[str,Optional[str]],None]):
        """Instantiate a UniversalLogger.

        Args:
            print_function: The function that will be called to 'print' any message
                given to the logger.
        """
        self._indent_cnt  = 0
        self._is_newline  = True
        self._print       = print_function
        self._bullets     = collections.defaultdict(lambda: '~', enumerate(['','*','>','-','+','~'])) 
        self._start_times = cast(List[float],[])

    @contextmanager
    def _with(self) -> Iterator[LoggerInterface]:
        try:
            self._indent_cnt += 1
            self._start_times.append(time.time())

            yield self

            if not self._is_newline: self.log('')
            self.log(f"finished after {round(time.time() - self._start_times[-1], 2)} seconds")

        except KeyboardInterrupt:
            raise

        except Exception as e:
            # we don't want to mask any information so we're not using the formally
            # defined exception chaining syntax (e.g., `raise LoggedException from e`)
            # instead we add our own dunder attribute to indicate that the exception has
            # been logged. This is friendlier when debugging since some Python debuggers
            # don't ever look at the __cause__ attribute set by the explicit syntax
            self.log_exception(e, f"exception after {round(time.time() - self._start_times[-1], 2)} seconds:")
            raise e

        finally:
            self._start_times.pop()
            self._indent_cnt -= 1

    def _prefix(self) -> str:
        indent = '  ' * self._indent_cnt
        bullet = self._bullets[self._indent_cnt]

        return datetime.now().strftime('%Y-%m-%d %H:%M:%S') + ' ' + indent + bullet + (' ' if bullet != '' else '')

    def log(self, message: str, end: str = None) -> ContextManager[LoggerInterface]:
        """Log a message.
        
        Args:
            message: The message that should be logged.
            end: The string that should be written at the end of the given message.

        Returns:
            A ContextManager that maintains the indentation level of the logger.
            Calling `__enter__` on the manager increases the indentation the loggers 
            indentation while calling `__exit__` decreases the logger's indentation.
        """
        if self._is_newline:
            message = self._prefix() + message

        self._print(message, end)

        self._is_newline = (end is None or end == '\n')

        return self._with()

    def log_exception(self, exception: Exception, preamble:str = "") -> None:
        """log an exception if it hasn't already been logged."""

        if not hasattr(exception, '__logged__'):
            setattr(exception, '__logged__', True)
            if not self._is_newline: self.log('')
            self.log(f"{preamble} {exception}".strip())


class ConsoleLogger(UniversalLogger):
    """An implementation of the UniversalLogger that writes to console."""
    def __init__(self) -> None:
        super().__init__(print_function=lambda m,e: print(m,end=e))

class NoneLogger(UniversalLogger):
    """An implementation of the UniversalLogger that writes to nowhere."""
    def __init__(self) -> None:
        super().__init__(print_function=lambda m,e: None)

class LoggedException(Exception):
    """An exception that has been logged but not handled."""

class ExecutionContext:
    """Create a global execution context to allow easy mocking and modification.

    In short, So long as the same modulename is always used to import and the import
    always occurs on the same thread I'm fairly confident this pattern will always work.

    In long, I'm somewhat unsure about this pattern for the following reasons:
        > While there seems concensus that multi-import doesn't repeat [1] it may if different modulenames are used [2]
            [1] https://stackoverflow.com/a/19077396/1066291
            [2] https://stackoverflow.com/q/13392038/1066291

        > Python 3.7 added in explicit context management in [3,4] but this implementation is thread local only
            [3] https://www.python.org/dev/peps/pep-0567/
            [4] https://docs.python.org/3/library/contextvars.html
    """

    TemplatingEngine: TemplatingEngine               = TemplatingEngine()
    CobaConfig      : CobaConfig                     = CobaConfig()
    FileCache       : CacheInterface[str, IO[bytes]] = NoneCache()
    Logger          : LoggerInterface                = ConsoleLogger()

    if CobaConfig.file_cache["type"] == "disk":
        FileCache = DiskCache(CobaConfig.file_cache["directory"])

    if CobaConfig.file_cache["type"] == "memory":
        FileCache = MemoryCache[str, IO[bytes]]()