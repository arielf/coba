import time
import shutil
import threading
import unittest

from itertools import count
from contextlib import contextmanager
from pathlib import Path

from coba.config import DiskCacher, MemoryCacher, NullCacher, ConcurrentCacher
from coba.exceptions import CobaException

class IterCacher(MemoryCacher):
    def get(self,key):
        return iter(super().get(key))

class MaxCountCacher:
    def __init__(self, cacher, pause_once_on = None):
        self._cacher = cacher
        self._cur_count = 0
        self.max_count = 0

        self._paused     = False
        self._pause_on   = pause_once_on
        self._pause_cond = threading.Condition()

    @contextmanager
    def count_context(self):
        self._cur_count += 1
        self.max_count = max(self._cur_count, self.max_count)
        time.sleep(0.1)
        yield

        self._cur_count -= 1

    def release(self):
        with self._pause_cond:
            self._pause_cond.notify_all()

    def _try_pause(self,method):
        if self._pause_on == method and not self._paused:
            self._paused = True
            with self._pause_cond:
                self._pause_cond.wait()

    def __contains__(self,key):
        return key in self._cacher

    def get(self,key):
        with self.count_context():
            self._try_pause("get")
            return self._cacher.get(key)

    def put(self,key,val):
        with self.count_context():
            self._try_pause("put")
            self._cacher.put(key,val)

    def rmv(self,key):
        with self.count_context():
            self._try_pause("rmv")
            self._cacher.rmv(key)

    def get_put(self, key, getter):
        with self.count_context():
            self._try_pause("get_put")
            return self._cacher.get_put(key, getter)

class NullCacher_Tests(unittest.TestCase):

    def test_put_does_nothing(self):
        NullCacher().put("abc", "abc")
        self.assertNotIn("abc", NullCacher())
    
    def test_get_throws_exception(self):
        with self.assertRaises(Exception) as e:
            NullCacher().get("abc")

    def test_rmv_does_nothing(self):
        NullCacher().rmv("abc")

class MemoryCacher_Tests(unittest.TestCase):

    def test_put_works_correctly(self):
        cacher = MemoryCacher()
        cacher.put("abc", "abc")
        self.assertIn("abc", cacher)
    
    def test_get_works_correctly(self):
        cacher = MemoryCacher()
        cacher.put("abc", "abcd")
        self.assertIn("abc", cacher)
        self.assertEqual(cacher.get("abc"), "abcd")

    def test_rmv_works_correctly(self):
        cacher = MemoryCacher()
        cacher.put("abc", "abcd")
        self.assertIn("abc", cacher)
        cacher.rmv("abc")
        self.assertNotIn("abc", cacher)
        cacher.rmv("abc")

class DiskCacher_Tests(unittest.TestCase):
    Cache_Test_Dir = Path("coba/tests/.temp/cache_tests/")
    
    def setUp(self):

        if self.Cache_Test_Dir.exists():
            shutil.rmtree(self.Cache_Test_Dir)

        self.Cache_Test_Dir.mkdir()

    def tearDown(self) -> None:
        
        if self.Cache_Test_Dir.exists():
            shutil.rmtree(self.Cache_Test_Dir)

    def test_creates_directory(self):
        cache = DiskCacher(self.Cache_Test_Dir / "folder1/folder2")
        cache.put("test.csv", [b"test"])
        self.assertTrue("test.csv" in cache)

    def test_creates_directory2(self):
        cache = DiskCacher(None)
        cache.cache_directory = self.Cache_Test_Dir / "folder1/folder2"
        cache.put("test.csv", [b"test"])
        self.assertTrue("test.csv" in cache)
            
    def test_write_csv_to_cache(self):

        cache = DiskCacher(self.Cache_Test_Dir)
        self.assertFalse("test.csv"    in cache)
        cache.put("test.csv", [b"test"])
        self.assertTrue("test.csv" in cache)
        self.assertEqual(list(cache.get("test.csv")), [b"test"])
    
    def test_write_multiline_csv_to_cache(self):

        cache = DiskCacher(self.Cache_Test_Dir)
        self.assertFalse("test.csv"    in cache)
        cache.put("test.csv", [b"test", b"test2"])
        self.assertTrue("test.csv" in cache)
        self.assertEqual(list(cache.get("test.csv")), [b"test", b"test2"])

    def test_rmv_csv_from_cache(self):

        cache = DiskCacher(self.Cache_Test_Dir)
        self.assertFalse("test.csv"    in cache)
        cache.put("test.csv", [b"test"])
        self.assertTrue("test.csv"    in cache)
        cache.rmv("test.csv")
        self.assertFalse("test.csv"    in cache)
        cache.rmv("test.csv")

    def test_get_corrupted_cache(self):

        #this is the md5 hexdigest of "text.csv" (531f844bd184e913b050d49856e8d438)
        (self.Cache_Test_Dir / "text.csv.gz").write_text("abcd")
        
        with self.assertRaises(Exception) as e:
            list(DiskCacher(self.Cache_Test_Dir).get("text.csv"))
        
        self.assertTrue((self.Cache_Test_Dir / "text.csv.gz").exists())
        
        DiskCacher(self.Cache_Test_Dir).rmv("text.csv")
        self.assertFalse((self.Cache_Test_Dir / "text.csv.gz").exists())

    def test_put_corrupted_cache(self):

        def bad_data():
            yield b'test1'
            raise Exception()
            yield b'test2'
        
        with self.assertRaises(Exception) as e:
            DiskCacher(self.Cache_Test_Dir).put("text.csv", bad_data())
        
        self.assertNotIn("text.csv", DiskCacher(self.Cache_Test_Dir))
        self.assertFalse((self.Cache_Test_Dir / "text.csv.gz").exists())

    def test_None_cach_dir(self):
        cacher = DiskCacher(None)

        self.assertNotIn('a', cacher)
        cacher.get("a")
        cacher.put("a", [b'123'])

    def test_bad_file_key(self):
        with self.assertRaises(CobaException):
            self.assertFalse("abcs/:/123/!@#" in DiskCacher(self.Cache_Test_Dir))

    def test_get_put_multiline_csv_to_cache(self):
        cache = DiskCacher(self.Cache_Test_Dir)
        self.assertFalse("test.csv" in cache)        
        self.assertEqual(list(cache.get_put("test.csv", lambda: [b"test", b"test2"])), [b"test", b"test2"])
        self.assertEqual(list(cache.get("test.csv")), [b"test", b"test2"])
        self.assertEqual(list(cache.get_put("test.csv", lambda: None)), [b"test", b"test2"])

    def test_get_put_None_cache_dir(self):
        cache = DiskCacher(None)
        self.assertFalse("test.csv" in cache)        
        self.assertEqual(list(cache.get_put("test.csv", lambda: [b"test", b"test2"])), [b"test", b"test2"])
        self.assertFalse("test.csv" in cache)        

class ConcurrentCacher_Test(unittest.TestCase):

    def test_put_works_correctly_single_thread(self):
        cacher = ConcurrentCacher(MemoryCacher(), {}, threading.Lock(), threading.Condition())
        cacher.put("abc", "abc")
        self.assertIn("abc", cacher)

    def test_get_works_correctly_single_thread(self):
        cacher = ConcurrentCacher(MemoryCacher(), {}, threading.Lock(), threading.Condition())
        cacher.put("abc", "abcd")
        self.assertIn("abc", cacher)
        self.assertEqual(cacher.get("abc"), "abcd")

    def test_get_iter_works_correctly_single_thread(self):
        cacher = ConcurrentCacher(IterCacher(), {}, threading.Lock(), threading.Condition())
        cacher.put("abc", [1,2,3])
        self.assertEqual(list(cacher.get("abc")), [1,2,3])
        self.assertEqual(list(cacher.get("abc")), [1,2,3])
        self.assertEqual(0, cacher._dict["abc"])

    def test_rmv_works_correctly_single_thread(self):
        cacher = ConcurrentCacher(MemoryCacher(), {}, threading.Lock(), threading.Condition())
        cacher.put("abc", "abcd")
        self.assertIn("abc", cacher)
        cacher.rmv("abc")
        self.assertNotIn("abc", cacher)
        cacher.rmv("abc")

    def test_get_then_get_works_correctly_with_conflicting_keys_multi_thread(self):
        base_cacher = MaxCountCacher(MemoryCacher(),pause_once_on="get")
        curr_cacher = ConcurrentCacher(base_cacher , {}, threading.Lock(), threading.Condition())

        curr_cacher.put(1,1)

        def thread_1():
            curr_cacher.get(1)

        def thread_2():
            curr_cacher.get(1)

        t1 = threading.Thread(None, thread_1)
        t2 = threading.Thread(None, thread_2)

        t1.daemon = True
        t2.daemon = True

        t1.start()
        time.sleep(.1)
        
        t2.start()
        t2.join()

        self.assertTrue(t1.is_alive())
        base_cacher.release()

        t1.join()

        self.assertEqual(2, base_cacher.max_count)
        self.assertEqual(curr_cacher.get(1), 1)

    def test_get_then_get_works_correctly_sans_conflicting_keys_multi_thread(self):
        base_cacher = MaxCountCacher(MemoryCacher(),pause_once_on="get")
        curr_cacher = ConcurrentCacher(base_cacher , {}, threading.Lock(), threading.Condition())

        curr_cacher.put(1,1)
        curr_cacher.put(2,2)

        def thread_1():
            curr_cacher.get(1)

        def thread_2():
            curr_cacher.get(2)

        t1 = threading.Thread(None, thread_1)
        t2 = threading.Thread(None, thread_2)

        t1.daemon = True
        t2.daemon = True

        t1.start()
        time.sleep(.1)
        
        t2.start()
        t2.join()

        self.assertTrue(t1.is_alive())
        base_cacher.release()

        t1.join()

        self.assertEqual(2, base_cacher.max_count)
        self.assertEqual(curr_cacher.get(1), 1)
        self.assertEqual(curr_cacher.get(2), 2)

    def test_put_then_put_works_correctly_with_conflicting_keys_multi_thread(self):
        base_cacher = MaxCountCacher(MemoryCacher(),pause_once_on="put")
        curr_cacher = ConcurrentCacher(base_cacher , {}, threading.Lock(), threading.Condition())

        def thread_1():
            curr_cacher.put(1,2)

        def thread_2():
            curr_cacher.put(1,3)

        t1 = threading.Thread(None, thread_1)
        t2 = threading.Thread(None, thread_2)

        t1.daemon = True
        t2.daemon = True

        t1.start()
        time.sleep(.1)
        t2.start()
        time.sleep(.1)

        self.assertTrue(t1.is_alive())
        self.assertTrue(t2.is_alive())
        
        base_cacher.release()

        t1.join()
        t2.join()

        self.assertEqual(1, base_cacher.max_count)
        self.assertEqual(curr_cacher.get(1), 3)

    def test_put_then_put_works_correctly_sans_conflicting_keys_multi_thread(self):
        base_cacher = MaxCountCacher(MemoryCacher(),pause_once_on="put")
        curr_cacher = ConcurrentCacher(base_cacher , {}, threading.Lock(), threading.Condition())

        def thread_1():
            curr_cacher.put(1,2)

        def thread_2():
            curr_cacher.put(2,3)

        t1 = threading.Thread(None, thread_1)
        t2 = threading.Thread(None, thread_2)

        t1.daemon = True
        t2.daemon = True

        t1.start()
        time.sleep(.1)
        
        t2.start()
        t2.join()

        self.assertTrue(t1.is_alive())
        base_cacher.release()

        t1.join()

        self.assertEqual(2, base_cacher.max_count)
        self.assertEqual(curr_cacher.get(1), 2)
        self.assertEqual(curr_cacher.get(2), 3)

    def test_put_then_get_works_correctly_with_conflicting_keys_multi_thread(self):
        base_cacher = MaxCountCacher(MemoryCacher(),pause_once_on="put")
        curr_cacher = ConcurrentCacher(base_cacher , {}, threading.Lock(), threading.Condition())

        def thread_1():
            curr_cacher.put(1,2)

        def thread_2():
            curr_cacher.get(1)

        t1 = threading.Thread(None, thread_1)
        t2 = threading.Thread(None, thread_2)

        t1.daemon = True
        t2.daemon = True

        t1.start()
        time.sleep(.1)
        t2.start()
        time.sleep(.05)

        self.assertTrue(t1.is_alive())
        self.assertTrue(t2.is_alive())

        base_cacher.release()

        t1.join()
        t2.join()

        self.assertEqual(1, base_cacher.max_count)
        self.assertEqual(curr_cacher.get(1), 2)

    def test_put_then_get_works_correctly_sans_conflicting_keys_multi_thread(self):
        
        base_cacher = MaxCountCacher(MemoryCacher(),pause_once_on="put")
        curr_cacher = ConcurrentCacher(base_cacher , {}, threading.Lock(), threading.Condition())

        base_cacher._cacher.put(2,1)

        def thread_1():
            curr_cacher.put(1,2)

        def thread_2():
            curr_cacher.get(2)

        t1 = threading.Thread(None, thread_1)
        t2 = threading.Thread(None, thread_2)

        t1.daemon = True
        t2.daemon = True

        t1.start()
        time.sleep(.01)
        t2.start()
        t2.join()

        self.assertTrue(t1.is_alive())
        self.assertFalse(t2.is_alive())

        base_cacher.release()
        t1.join()

        self.assertEqual(2, base_cacher.max_count)
        self.assertEqual(curr_cacher.get(1), 2)

    def test_get_then_put_works_correctly_with_conflicting_keys_multi_thread(self):
        base_cacher = MaxCountCacher(MemoryCacher(),pause_once_on="get")
        curr_cacher = ConcurrentCacher(base_cacher , {}, threading.Lock(), threading.Condition())

        curr_cacher.put(1,1)

        def thread_1():
            curr_cacher.get(1)

        def thread_2():
            curr_cacher.put(1,2)

        t1 = threading.Thread(None, thread_1)
        t2 = threading.Thread(None, thread_2)

        t1.daemon = True
        t2.daemon = True

        t1.start()
        time.sleep(.1)
        t2.start()
        time.sleep(.05)

        self.assertTrue(t1.is_alive())
        self.assertTrue(t2.is_alive())

        base_cacher.release()

        t1.join()
        t2.join()

        self.assertEqual(1, base_cacher.max_count)
        self.assertEqual(curr_cacher.get(1), 2)

    def test_get_then_put_works_correctly_sans_conflicting_keys_multi_thread(self):
        base_cacher = MaxCountCacher(MemoryCacher(),pause_once_on="get")
        curr_cacher = ConcurrentCacher(base_cacher , {}, threading.Lock(), threading.Condition())

        base_cacher._cacher.put(1,1)

        def thread_1():
            curr_cacher.get(1)

        def thread_2():
            curr_cacher.put(2,2)

        t1 = threading.Thread(None, thread_1)
        t2 = threading.Thread(None, thread_2)

        t1.daemon = True
        t2.daemon = True

        t1.start()
        time.sleep(.01)
        t2.start()
        t2.join()

        self.assertTrue(t1.is_alive())
        self.assertFalse(t2.is_alive())

        base_cacher.release()
        t1.join()

        self.assertEqual(2, base_cacher.max_count)
        self.assertEqual(curr_cacher.get(1), 1)
        self.assertEqual(curr_cacher.get(2), 2)

    def test_get_put_put_then_get_put_get_works_correctly_with_conflicting_keys_multi_thread(self):
        base_cacher = MaxCountCacher(MemoryCacher(),pause_once_on="get_put")
        curr_cacher = ConcurrentCacher(base_cacher , {}, threading.Lock(), threading.Condition())

        def thread_1():
            curr_cacher.get_put(1,lambda: 1)

        def thread_2():
            curr_cacher.get_put(1,lambda: 2)

        t1 = threading.Thread(None, thread_1)
        t2 = threading.Thread(None, thread_2)

        t1.daemon = True
        t2.daemon = True

        t1.start()
        time.sleep(.1)
        t2.start()
        time.sleep(.05)

        self.assertTrue(t1.is_alive())
        self.assertTrue(t2.is_alive())

        base_cacher.release()

        t1.join()
        t2.join()

        self.assertEqual(1, base_cacher.max_count)
        self.assertEqual(curr_cacher.get(1), 1)

    def test_get_put_put_then_get_put_get_works_correctly_sans_conflicting_keys_multi_thread(self):
        base_cacher = MaxCountCacher(MemoryCacher(),pause_once_on="get_put")
        curr_cacher = ConcurrentCacher(base_cacher , {}, threading.Lock(), threading.Condition())

        def thread_1():
            curr_cacher.get_put(1,lambda: 1)

        def thread_2():
            curr_cacher.get_put(2,lambda: 2)

        t1 = threading.Thread(None, thread_1)
        t2 = threading.Thread(None, thread_2)

        t1.daemon = True
        t2.daemon = True

        t1.start()
        time.sleep(.01)

        t2.start()
        t2.join()

        self.assertTrue(t1.is_alive())
        base_cacher.release()

        t1.join()

        self.assertEqual(2, base_cacher.max_count)
        self.assertEqual(curr_cacher.get(1), 1)
        self.assertEqual(curr_cacher.get(2), 2)

    def test_get_put_put_then_get_put_get_iter_works_correctly_sans_conflicting_keys_multi_thread(self):
        base_cacher = MaxCountCacher(IterCacher(),pause_once_on="get_put")
        curr_cacher = ConcurrentCacher(base_cacher , {}, threading.Lock(), threading.Condition())

        def thread_1():
            curr_cacher.get_put(1,lambda: [1])

        def thread_2():
            curr_cacher.get_put(2,lambda: [2])

        t1 = threading.Thread(None, thread_1)
        t2 = threading.Thread(None, thread_2)

        t1.daemon = True
        t2.daemon = True

        t1.start()
        time.sleep(.01)

        t2.start()
        t2.join()

        self.assertTrue(t1.is_alive())
        base_cacher.release()

        t1.join()

        self.assertEqual(2, base_cacher.max_count)
        self.assertEqual(list(curr_cacher.get(1)), [1])
        self.assertEqual(list(curr_cacher.get(2)), [2])

    def test_get_put_get_then_get_put_get_works_correctly_with_conflicting_sans_multi_thread(self):
        base_cacher = MaxCountCacher(MemoryCacher(),pause_once_on="get")
        curr_cacher = ConcurrentCacher(base_cacher , {}, threading.Lock(), threading.Condition())

        curr_cacher.put(1,1)

        def thread_1():
            curr_cacher.get_put(1,lambda: 1)

        def thread_2():
            curr_cacher.get_put(1,lambda: 2)

        t1 = threading.Thread(None, thread_1)
        t2 = threading.Thread(None, thread_2)

        t1.daemon = True
        t2.daemon = True

        t1.start()
        time.sleep(.01)

        t2.start()
        t2.join()

        self.assertTrue(t1.is_alive())
        base_cacher.release()

        t1.join()

        self.assertEqual(2, base_cacher.max_count)
        self.assertEqual(curr_cacher.get(1), 1)

if __name__ == '__main__':
    unittest.main()