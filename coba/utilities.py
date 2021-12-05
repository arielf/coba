"""Simple one-off utility methods with no clear home."""

import sys
import os
import warnings
import importlib

from collections import defaultdict
from io import UnsupportedOperation
from contextlib import contextmanager
from typing import IO

from coba.exceptions import CobaExit

def coba_exit(message:str):
    warnings.filterwarnings("ignore",message="To exit: use 'exit', 'quit', or Ctrl-D.")
    raise CobaExit(message) from None

@contextmanager
def redirect_stderr(to: IO[str]):
    """Redirect stdout for both C and Python.

    Remarks:
        This code comes from https://stackoverflow.com/a/17954769/1066291. Because this modifies
        global pointers this code is not "thread-safe". This limitation is also true of the built-in
        Python modules such as `contextlib.redirect_stdout` and `contextlib.redirect_stderr`. See
        https://docs.python.org/3/library/contextlib.html#contextlib.redirect_stdout for more info.
    """
    try:
        #we assume that this fd is the same
        #one that is used by our C library
        stderr_fd = sys.stderr.fileno()

        def _redirect_stderr(redirect_stderr_fd):
            
            #first we flush Python's stderr. It should be noted that this
            #doesn't close the file descriptor (i.e., sys.stderr.fileno())
            #or Python's wrapper around the stderr_fd.
            sys.stderr.flush()
        
            # next we change the stderr_fd to point to the
            # file contained in the redirect_stderr_fd.
            # If C has anything buffered for stderr it
            # will now go to the new fd. There do appear
            # to be ways to flush C buffers from Python 
            # but I'm not sure it is worth it given the
            # amount of complexity it adds to the code.
            # This change also means that sys.stderr now
            # points to a new file since sys.stderr points
            # to whatever file is at stderr_fd
            os.dup2(redirect_stderr_fd, stderr_fd)

        # when we dup there are now two fd's
        # pointing to the same file. Closing
        # one of these doesn't close the other.
        # therefore it is on us to close the
        # duplicate fd we make here before ending.
        old_stderr_fd = os.dup(stderr_fd)
        new_stderr_fd = to.fileno()

        try:
            _redirect_stderr(new_stderr_fd)
            yield # allow code to be run with the redirected stderr
        finally:
            _redirect_stderr(old_stderr_fd) 
            os.close(old_stderr_fd)
    except UnsupportedOperation: # pragma: no cover
        #if for some reason we weren't able to redirect
        #then simply move on. No reason to stop working.
        pass

class PackageChecker:
    
    @staticmethod
    def matplotlib(caller_name: str) -> None:
        """Raise ImportError with detailed error message if matplotlib is not installed.

        Functionality requiring matplotlib should call this helper and then lazily import.

        Args:    
            caller_name: The name of the caller that requires matplotlib.

        Remarks:
            This pattern borrows heavily from sklearn. As of 6/20/2020 sklearn code could be found
            at https://github.com/scikit-learn/scikit-learn/blob/master/sklearn/utils/__init__.py
        """
        try:
            importlib.import_module('matplotlib')
        except ImportError:
            PackageChecker._handle_import_error(caller_name, "matplotlib")

    @staticmethod
    def vowpalwabbit(caller_name: str) -> None:
        """Raise ImportError with detailed error message if vowpalwabbit is not installed.

        Functionality requiring vowpalwabbit should call this helper and then lazily import.

        Args:    
            caller_name: The name of the caller that requires vowpalwabbit.

        Remarks:
            This pattern was inspired by sklearn (see `PackageChecker.matplotlib` for more information).
        """

        try:
            importlib.import_module('vowpalwabbit')
        except ImportError as e:
            PackageChecker._handle_import_error(caller_name, "vowpalwabbit")

    @staticmethod
    def pandas(caller_name: str) -> None:
        """Raise ImportError with detailed error message if pandas is not installed.

        Functionality requiring pandas should call this helper and then lazily import.

        Args:
            caller_name: The name of the caller that requires pandas.

        Remarks:
            This pattern was inspired by sklearn (see `PackageChecker.matplotlib` for more information).
        """
        try:
            importlib.import_module('pandas')
        except ImportError:
            PackageChecker._handle_import_error(caller_name, "pandas")

    @staticmethod
    def numpy(caller_name: str) -> None:
        """Raise ImportError with detailed error message if numpy is not installed.

        Functionality requiring numpy should call this helper and then lazily import.

        Args:
            caller_name: The name of the caller that requires numpy.

        Remarks:
            This pattern was inspired by sklearn (see `PackageChecker.matplotlib` for more information).
        """
        try:
            importlib.import_module('numpy')
        except ImportError:
            PackageChecker._handle_import_error(caller_name, "numpy")

    @staticmethod
    def sklearn(caller_name: str) -> None:
        """Raise ImportError with detailed error message if sklearn is not installed.

        Functionality requiring sklearn should call this helper and then lazily import.

        Args:
            caller_name: The name of the caller that requires sklearn.

        Remarks:
            This pattern was inspired by sklearn (see `PackageChecker.matplotlib` for more information).
        """
        try:
            importlib.import_module('sklearn')
        except ImportError:
            PackageChecker._handle_import_error(caller_name, "scikit-learn")

    def _handle_import_error(caller_name:str, pkg_name:str):
        coba_exit(f"ERROR: {caller_name} requires the {pkg_name} package. You can install this package via `pip install {pkg_name}`.")

class HashableDict(dict):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._hash = hash(tuple(self.items()))

    def __hash__(self) -> int:
        assert self._hash == hash(tuple(self.items()))
        return self._hash

class KeyDefaultDict(defaultdict):
    def __missing__(self, key):
        if self.default_factory is None:
            raise KeyError( key )
        else:
            value = self.default_factory(key)
            self[key] = value
            return value