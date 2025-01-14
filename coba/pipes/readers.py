import re
import csv
import collections.abc
import operator

from collections import deque, defaultdict
from itertools import islice, chain, count, product
from typing import Iterable, Sequence, List, Dict, Union, Any, Iterator, Pattern, Callable, Set, Tuple
from typing import MutableSequence, MutableMapping

from coba.exceptions import CobaException
from coba.encodings import Encoder, OneHotEncoder

from coba.pipes.primitives import Filter

class DenseWithMeta(collections.abc.MutableSequence):
    def __init__(self, values: Sequence[Any], headers: Dict[str,int] = {}, encoders: Sequence[Callable[[Any],Any]] = []) -> None:
        self._headers  = headers
        self._encoders = encoders
        self._values   = values

        self._removed  = 0
        self._offsets  = [0]*len(values)
        self._encoded  = [not encoders]*len(values)

    def __getitem__(self, index: Union[str,int]) -> Any:
        index = self._headers[index] if index in self._headers else self._offsets[index] + index

        if not self._encoded[index] and self._encoders:
            self._values[index] = self._encoders[index](self._values[index])
            self._encoded[index] = True

        return self._values[index]

    def __setitem__(self, index: Union[str,int], value: Any) -> None:
        index = self._headers[index] if index in self._headers else self._offsets[index] + index
        self._values[index] = value
        self._encoded[index] = True

    def __delitem__(self, index: Union[str,int]):
        old_index = self._headers[index] if index in self._headers else self._offsets[index] + index
        new_index = self._old_indexes().index(old_index)

        self._offsets.pop(new_index)

        for i in range(new_index, len(self._offsets)):
            self._offsets[i] += 1

    def __len__(self) -> int:
        return len(self._offsets)

    def insert(self, index: int, value:Any):
        raise NotImplementedError()

    def _old_indexes(self) -> Sequence[int]:
        return list(map(operator.add,count(),self._offsets))

    def __eq__(self, __o: object) -> bool:
        return list(self).__eq__(__o)

    def __repr__(self) -> str:
        return str(list(self))

    def __str__(self) -> str:
        return str(list(self))

class SparseWithMeta(collections.abc.MutableMapping):

    def __init__(self, values: Dict[Any,str], headers: Dict[str,Any] = {}, encoders: Dict[Any,Callable[[Any],Any]] = {}) -> None:
        self._headers  = headers
        self._encoders = encoders
        self._values   = values

        self._removed: Set[Any] = set()
        self._encoded: Dict[Any,bool] = defaultdict(bool)
    
    def __getitem__(self, index: Union[str,int]) -> Any:
        index = self._headers[index] if index in self._headers else index
        if index in self._removed: raise KeyError(index)

        if not self._encoded[index] and self._encoders:
            self._values[index] = self._encoders[index](self._values[index])
            self._encoded[index] = True

        return self._values[index]

    def __setitem__(self, index: Union[str,int], value: Any) -> None:
        index = self._headers[index] if index in self._headers else index
        if index in self._removed: raise KeyError(index)
        self._values[index] = value

    def __delitem__(self, index: Union[str,int]):
        index = self._headers[index] if index in self._headers else index
        if index in self._removed: raise KeyError(index)
        self._removed.add(index)

    def __len__(self) -> int:
        return len(self._values) - len(self._removed)

    def __iter__(self) -> Iterator[Any]:
        return iter(self._values.keys()-self._removed)

    def __eq__(self, __o: object) -> bool:
        return dict(self.items()).__eq__(__o)

    def __repr__(self) -> str:
        return str(dict(self))

    def __str__(self) -> str:
        return str(dict(self))

class CsvReader(Filter[Iterable[str], Iterable[MutableSequence]]):
    """A filter capable of parsing CSV formatted data."""
    
    def __init__(self, has_header: bool=False, **dialect):
        """Instantiate a CsvReader.
        
        Args:
            has_header: Indicates if the CSV data has a header row.
            **dialect: This has the same values as Python's csv.reader dialect.
        """
        self._dialect    = dialect
        self._has_header = has_header 

    def filter(self, items: Iterable[str]) -> Iterable[MutableSequence]:

        lines = iter(csv.reader(iter(filter(None,(i.strip() for i in items))), **self._dialect))

        if self._has_header:
            headers = dict(zip(next(lines), count()))

        for line in lines:
            yield line if not self._has_header else DenseWithMeta(line,headers)

class ArffReader(Filter[Iterable[str], Iterable[Union[MutableSequence,MutableMapping]]]):
    """A filter capable of parsing ARFF formatted data.

    For a complete description of the ARFF format see `here`__.

    __ https://waikato.github.io/weka-wiki/formats_and_processing/arff_stable/
    """

    #this class has been highly highly optimized. Before modifying anything run 
    #Performance_Tests.test_arffreader_performance to get a performance baseline.

    def __init__(self, 
        cat_as_str: bool =False, 
        skip_encoding: bool = False, 
        lazy_encoding: bool = True, 
        header_indexing: bool = True):
        """Instantiate an ArffReader.
        
        Args:
            cat_as_str: Indicates that categorical features should be encoded as a string rather than one hot encoded. 
            skip_encoding: Indicates that features should not be encoded (this means all features will be strings).
            lazy_encoding: Indicates that features should be encoded lazily (this can save time if rows will be dropped).
            header_indexing: Indicates that header data should be preserved so rows can be indexed by header name. 
        """

        self._quotes = '"'+"'"

        self._cat_as_str      = cat_as_str 
        self._skip_encoding   = skip_encoding
        self._lazy_encoding   = lazy_encoding
        self._header_indexing = header_indexing 

    def filter(self, source: Iterable[str]) -> Iterable[Union[MutableSequence,MutableMapping]]:
        headers  : List[str    ] = []
        encodings: List[Encoder] = []

        source = (line.strip() for line in source)
        source = (line for line in source if line and not line.startswith("%"))

        lines = iter(source)

        r_space = re.compile("(\s+)")
        for line in lines:
            if line[0:10].lower() == "@attribute":
                header, encoding = tuple(self._pattern_split(line[11:], r_space, n=2))
                headers.append(header)
                encodings.append(encoding)
            elif line[0:5].lower() == "@data":
                break

        try:
            first_data_line = next(lines)
        except StopIteration:
            return []

        is_dense = not (first_data_line.startswith('{') and first_data_line.endswith('}'))
        encoders = list(self._encoders(encodings,is_dense))

        if is_dense:
            return self._parse_dense_data(chain([first_data_line], lines), headers, encoders)
        else:
            return self._parse_sparse_data(chain([first_data_line], lines), headers, encoders)

    def _encoders(self, encodings: Sequence[str], is_dense:bool) -> Encoder:
        numeric_types = ('numeric', 'integer', 'real')
        string_types  = ("string", "date", "relational")
        r_comma       = None
        identity      = lambda x: None if x=="?" else x.strip()

        for encoding in encodings:
            
            if self._skip_encoding:
                yield identity
            elif encoding in numeric_types: 
                yield lambda x: None if x=="?" else float(x)
            elif encoding.startswith(string_types):
                yield identity
            elif encoding.startswith('{'):
                r_comma = r_comma or re.compile("(,)")
                categories = list(self._pattern_split(encoding[1:-1], r_comma))
                
                if not is_dense:
                    #there is a bug in ARFF where the first class value in an ARFF class can will dropped from the 
                    #actual data because it is encoded as 0. Therefore, our ARFF reader automatically adds a 0 value 
                    #to all sparse categorical one-hot encoders to protect against this.
                    categories = ["0"] + categories

                def encoder(x:str,cats=categories,get=OneHotEncoder(categories)._onehots.__getitem__):

                    x=x.strip()

                    if x =="?":
                        return None

                    if x not in cats and x[0] in self._quotes and x[0]==x[-1] and len(x) > 1:
                        x = x[1:-1]

                    if x not in cats:
                        raise CobaException("We were unable to find one of the categorical values in the arff data.")

                    return x if self._cat_as_str else get(x)

                yield encoder
            else:
                raise CobaException(f"An unrecognized encoding was found in the arff attributes: {encoding}.")

    def _parse_dense_data(self,
        lines: Iterable[str],
        headers: Sequence[str],
        encoders: Sequence[Encoder]) -> Iterable[Union[MutableSequence,MutableMapping]]:

        headers_dict        = dict(zip(headers,count()))
        possible_dialects   = self._possible_dialects()

        dialect             = possible_dialects.pop()
        fallback_delimieter = None

        for i,line in enumerate(lines):

            if dialect is not None:
                final = next(csv.reader([line], dialect=dialect))

                while len(final) != len(headers) and possible_dialects:
                    dialect = possible_dialects.pop()
                    final   = next(csv.reader([line], dialect=dialect))

                if len(final) != len(headers): dialect = None

            if dialect is None:
                #None of the csv dialects we tried were successful at parsing
                #we fall back now to a slightly slower, but more flexible, parser

                if fallback_delimieter is None:
                    #this isn't airtight but we can only infer so much.
                    fallback_delimieter = ',' if len(line.split(',')) > len(line.split('\t')) else "\t"

                line = deque(line.split(fallback_delimieter))
                final = []

                while line:
                    item = line.popleft().lstrip()

                    if item[0] in self._quotes:
                        quotechar = item[0]
                        while item.rstrip()[-1] != quotechar or item.rstrip()[-2] == "\\":
                            item += "," + line.popleft()
                        item = item.strip()[1:-1]

                    final.append(item.replace('\\',''))

            if len(final) != len(headers):
                raise CobaException(f"We were unable to parse line {i} in a way that matched the expected attributes.")

            final_headers  = headers_dict if self._header_indexing else {}
            final_encoders = encoders if self._lazy_encoding else []
            final_items    = final if self._lazy_encoding else [ e(f) for e,f in zip(encoders,final)]

            if not self._lazy_encoding and not self._header_indexing:
                yield final_items
            else:
                yield DenseWithMeta(final_items, final_headers, final_encoders)

    def _parse_sparse_data(self, 
        lines: Iterable[str], 
        headers: Sequence[str], 
        encoders: Sequence[Encoder]) -> Iterable[Union[MutableSequence,MutableMapping]]:

        headers_dict  = dict(zip(headers,count()))
        defaults_dict = { k:"0" for k in range(len(encoders)) if encoders[k]("0") != 0 }
        encoders_dict = dict(zip(count(),encoders))

        for i,line in enumerate(lines):

            keys_and_vals = re.split('\s*,\s*|\s+', line.strip("} {"))

            keys = list(map(int,keys_and_vals[0::2]))
            vals = keys_and_vals[1::2]

            if max(keys) >= len(headers) or min(keys) < 0:
                raise CobaException(f"We were unable to parse line {i} in a way that matched the expected attributes.")

            final = { **defaults_dict, ** dict(zip(keys,vals)) }

            final_headers  = headers_dict if self._header_indexing else {}
            final_encoders = encoders_dict if self._lazy_encoding else {}
            final_items    = final if self._lazy_encoding else { k:encoders[k](v) for k,v in final.items() }

            if not self._lazy_encoding and not self._header_indexing:
                yield final_items
            else:
                yield SparseWithMeta(final_items, final_headers, final_encoders)

    def _pattern_split(self, line: str, pattern: Pattern[str], n=None):

        items  = iter(pattern.split(line))
        count  = 0
        quotes = self._quotes

        try:
            while True:

                item = next(items).lstrip()
                if not item or pattern.match(item): continue

                count += 1
                if count == n: 
                    items = chain([item],items)
                    break

                if item[0] in quotes:
                    q  = item[0]
                    while item.rstrip()[-1] != q or item.rstrip()[-2]=="\\":
                        item += next(items)
                    item = item.rstrip()[1:-1]

                yield item.strip()

            yield "".join(items).strip()
        except StopIteration:
            pass

    def _possible_dialects(self):
        legal_quotechars = ['"', "'"]
        legal_delimeters = [",", "\t"]

        return [
            {"delimeter":d, "quotechar": q, "skipinitialspace":True} for d,q in product(legal_delimeters, legal_quotechars) 
        ]

class LibsvmReader(Filter[Iterable[str], Iterable[Tuple[MutableMapping,Any]]]):
    """A filter capable of parsing Libsvm formatted data.

    For a complete description of the libsvm format see `here`__ and `here`__.

    __ https://www.csie.ntu.edu.tw/~cjlin/libsvmtools/datasets/
    __ https://github.com/cjlin1/libsvm
    """
    def filter(self, lines: Iterable[str]) -> Iterable[Tuple[MutableMapping, Any]]:

        for line in filter(None,lines):

            items  = line.strip().split(' ')

            no_label_line = items[0] == '' or ":" in items[0]

            if not no_label_line:
                labels = items[0].split(',')
                row    = { int(k):float(v) for i in items[1:] for k,v in [i.split(":")] }
                yield (row, labels)

class ManikReader(Filter[Iterable[str], Iterable[Tuple[MutableMapping,Any]]]):
    """A filter capable of parsing Manik formatted data.

    For a complete description of the manik format see `here`__ and `here`__.

    __ http://manikvarma.org/downloads/XC/XMLRepository.html
    __ https://drive.google.com/file/d/1u7YibXAC_Wz1RDehN1KjB5vu21zUnapV/view
    """

    def filter(self, lines: Iterable[str]) -> Iterable[Tuple[MutableMapping, Any]]:
        # we skip first line because it just has metadata
        return LibsvmReader().filter(islice(lines,1,None))
