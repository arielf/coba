import unittest
import importlib.util

from collections import Counter

import coba.random

class CobaRandom_Tests(unittest.TestCase):

    def test_value_of_random(self):

        for _ in range(10000):
            n = coba.random.random()
            self.assertLessEqual(n,1)
            self.assertGreaterEqual(n,0)

    def test_zero_randoms(self):
        self.assertEqual([],coba.random.randoms(0))

    def test_value_of_randoms(self):

        numbers = coba.random.randoms(500000)
        
        self.assertEqual(len(numbers), 500000)

        for n in numbers:
            self.assertLessEqual(n, 1)
            self.assertGreaterEqual(n, 0)

    def test_value_of_shuffle(self):

        numbers = coba.random.shuffle(list(range(500000)))

        self.assertEqual(len(numbers), 500000)
        self.assertNotEqual(numbers, list(range(500000)))

    def test_empty_shuffle(self):
        self.assertEqual([], coba.random.shuffle([]))

    def test_coba_randoms_is_unchanged(self):
        coba.random.seed(10)

        actual_random_numbers = [ round(n,2) for n in coba.random.randoms(5) ]

        self.assertEqual([0.09, 0.18, 0.16, 0.98, 0.14], actual_random_numbers)

    def test_coba_choice_is_unchanged(self):

        coba.random.seed(10)

        choice = coba.random.choice(list(range(1000)), [1/1000]*1000)

        self.assertEqual(86, choice)

    def test_coba_shuffle_is_unchaged(self):

        coba.random.seed(10)

        shuffle = coba.random.shuffle(list(range(20)))

        self.assertEqual([1, 4, 0, 19, 6, 15, 3, 16, 11, 10, 7, 17, 13, 8, 9, 14, 18, 12, 5, 2],shuffle)

    def test_randoms_repeatability(self):

        coba.random.seed(10)

        actual_random_numbers_1 = coba.random.randoms(5)

        coba.random.seed(10)

        actual_random_numbers_2 = coba.random.randoms(5)

        self.assertSequenceEqual(actual_random_numbers_1, actual_random_numbers_2)

    def test_shuffles_repeatability(self):

        coba.random.seed(10)

        shuffle_1 = coba.random.shuffle([1,2,3,4,5])

        coba.random.seed(10)

        shuffle_2 = coba.random.shuffle([1,2,3,4,5])

        self.assertEqual(shuffle_1, shuffle_2)

    def test_choice_repeatability(self):

        coba.random.seed(10)

        choice_1 = coba.random.choice(list(range(1000)), [1/1000]*1000)

        coba.random.seed(10)

        choice_2 = coba.random.choice(list(range(1000)), [1/1000]*1000)

        self.assertEqual(choice_1, choice_2)

    def test_randint_is_bound_correctly_1(self):
        observed_ints = set()

        for i in range(100):
            observed_ints.add(coba.random.randint(0,2))

        self.assertIn(0, observed_ints)
        self.assertIn(1, observed_ints)
        self.assertIn(2, observed_ints)

    def test_randint_is_bound_correctly_2(self):
        observed_ints = set()

        for i in range(100):
            observed_ints.add(coba.random.randint(-3,-1))

        self.assertIn(-3, observed_ints)
        self.assertIn(-2, observed_ints)
        self.assertIn(-1, observed_ints)

    def test_choice1(self):
        choices = [(0,1), (1,0)]

        choice = coba.random.choice(choices)

        self.assertIsInstance(choice, tuple)

    def test_choice2(self):
        weights = [0.5,0.5]
        choices = [(0,1), (1,0)]

        choice = coba.random.choice(choices,weights)

        self.assertIsInstance(choice, tuple)

    def test_choice_exception(self):
        with self.assertRaises(ValueError) as e:
            coba.random.CobaRandom().choice([1,2,3],[0,0,0])

        self.assertIn("The sum of weights cannot be zero", str(e.exception))

    def test_randoms_n_0(self):
        with self.assertRaises(ValueError) as e:
            coba.random.CobaRandom().randoms(-1)

        self.assertIn("n must be an integer greater than or equal 0", str(e.exception))

    def test_randoms_n_2(self):
        cr1 = coba.random.CobaRandom(seed=1)
        cr2 = coba.random.CobaRandom(seed=1)

        cr2._m_is_power_of_2 = False

        self.assertEqual( cr1.randoms(3), cr2.randoms(3) )

    def test_gauss(self):
        
        expected = 0.626

        cr = coba.random.CobaRandom(seed=1)
        coba.random.seed(1)

        self.assertEqual(expected, round(cr.gauss(0,1),3))
        self.assertEqual(expected, round(coba.random.gauss(0,1),3))

    def test_gausses(self):

        expected = [0.626, -2.012]

        cr = coba.random.CobaRandom(seed=1)
        coba.random.seed(1)

        self.assertEqual(expected, [round(r,3) for r in cr.gausses(2,0,1)])
        self.assertEqual(expected, [round(r,3) for r in coba.random.gausses(2,0,1)])

    @unittest.skipUnless(importlib.util.find_spec("scipy"), "scipy is not installed so we must skip statistical tests")
    def test_gauss_normal(self):
        from scipy.stats import shapiro
        self.assertLess(0.00001, shapiro(coba.random.gausses(1000,0,1)).pvalue)

    @unittest.skipUnless(importlib.util.find_spec("scipy"), "scipy is not installed so we must skip statistical tests")
    def test_randint_uniform(self):
        from scipy.stats import chisquare

        frequencies = Counter([coba.random.randint(1,6) for _ in range(50000)])
        self.assertLess(0.00001, chisquare(list(frequencies.values())).pvalue)

    @unittest.skipUnless(importlib.util.find_spec("numpy"), "numpy is not installed so we must skip statistical tests")
    @unittest.skipUnless(importlib.util.find_spec("scipy"), "scipy is not installed so we must skip statistical tests")
    def test_randoms_uniform(self):
        import numpy as np
        from scipy.stats import chisquare

        frequencies = Counter(np.digitize(coba.random.randoms(50000), bins=[i/50 for i in range(50)]))
        self.assertLess(0.00001, chisquare(list(frequencies.values())).pvalue)
    
    @unittest.skipUnless(importlib.util.find_spec("scipy"), "scipy is not installed so we must skip statistical tests")
    def test_shuffle_is_unbiased(self):

        from scipy.stats import chisquare
        base = list(range(5))
        frequencies = Counter([tuple(coba.random.shuffle(base)) for _ in range(100000)])
        self.assertLess(0.00001, chisquare(list(frequencies.values())).pvalue)

if __name__ == '__main__':
    unittest.main()
