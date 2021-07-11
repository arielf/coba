import unittest

from itertools import repeat

from coba.config import CobaConfig, NoneLogger
from coba.simulations import Interaction, MemorySimulation, Shuffle, Take, PCA, Sort

CobaConfig.Logger = NoneLogger()

class Shuffle_Tests(unittest.TestCase):
    
    def test_shuffle(self):
        interactions = list(map(Interaction, repeat(1), repeat([1,2]), [[3,3],[4,4],[5,5]] ))
        
        simulation = MemorySimulation(interactions)
        shuffled_simulation = Shuffle(40).filter(simulation)

        self.assertEqual(3, len(simulation.interactions))
        self.assertEqual(interactions[0], simulation.interactions[0])
        self.assertEqual(interactions[1], simulation.interactions[1])
        self.assertEqual(interactions[2], simulation.interactions[2])

        self.assertEqual(3, len(shuffled_simulation.interactions))
        self.assertEqual(interactions[1], shuffled_simulation.interactions[0])
        self.assertEqual(interactions[2], shuffled_simulation.interactions[1])
        self.assertEqual(interactions[0], shuffled_simulation.interactions[2])

class Take_Tests(unittest.TestCase):
    
    def test_take1(self):

        interactions = list(map(Interaction, repeat(1), repeat([1,2]), [[3,3],[4,4],[5,5]]))

        simulation = MemorySimulation(interactions)
        take_simulation = Take(1).filter(simulation)

        self.assertEqual(1, len(take_simulation.interactions))
        self.assertEqual(interactions[0], take_simulation.interactions[0])

        self.assertEqual(3, len(simulation.interactions))
        self.assertEqual(interactions[0], simulation.interactions[0])
        self.assertEqual(interactions[1], simulation.interactions[1])
        self.assertEqual(interactions[2], simulation.interactions[2])

    def test_take2(self):
        interactions = list(map(Interaction, repeat(1), repeat([1,2]), [[3,3],[4,4],[5,5]]))

        simulation = MemorySimulation(interactions)
        take_simulation = Take(2).filter(simulation)

        self.assertEqual(2              , len(take_simulation.interactions))
        self.assertEqual(interactions[0], take_simulation.interactions[0])
        self.assertEqual(interactions[1], take_simulation.interactions[1])

        self.assertEqual(3              , len(simulation.interactions))
        self.assertEqual(interactions[0], simulation.interactions[0])
        self.assertEqual(interactions[1], simulation.interactions[1])
        self.assertEqual(interactions[2], simulation.interactions[2])

    def test_take3(self):
        interactions = list(map(Interaction, repeat(1), repeat([1,2]), [[3,3],[4,4],[5,5]] ))
        
        simulation = MemorySimulation(interactions)
        take_simulation = Take(3).filter(simulation)

        self.assertEqual(3              , len(take_simulation.interactions))
        self.assertEqual(interactions[0], take_simulation.interactions[0])
        self.assertEqual(interactions[1], take_simulation.interactions[1])
        self.assertEqual(interactions[2], take_simulation.interactions[2])

        self.assertEqual(3              , len(simulation.interactions))
        self.assertEqual(interactions[0], simulation.interactions[0])
        self.assertEqual(interactions[1], simulation.interactions[1])
        self.assertEqual(interactions[2], simulation.interactions[2])

    def test_take4(self):
        interactions = list(map(Interaction, repeat(1), repeat([1,2]), [[3,3],[4,4],[5,5]]))
        
        simulation = MemorySimulation(interactions)
        take_simulation = Take(4).filter(simulation)

        self.assertEqual(3, len(simulation.interactions))
        self.assertEqual(0, len(take_simulation.interactions))

    def test_repr(self):
        self.assertEqual('{"Take":2}', str(Take(2)))
        self.assertEqual('{"Take":null}', str(Take(None)))

class Interaction_Tests(unittest.TestCase):

    def test_constructor_no_context(self) -> None:
        Interaction(None, [1,2], [1,2])

    def test_constructor_context(self) -> None:
        Interaction((1,2,3,4), [1,2], [1,2])

    def test_context_correct_1(self) -> None:
        self.assertEqual(None, Interaction(None, [1,2], [1,2]).context)

    def test_actions_correct_1(self) -> None:
        self.assertSequenceEqual([1,2], Interaction(None, [1,2], [1,2]).actions)

    def test_actions_correct_2(self) -> None:
        self.assertSequenceEqual(["A","B"], Interaction(None, ["A","B"], [1,2]).actions)

    def test_actions_correct_3(self) -> None:
        self.assertSequenceEqual([(1,2), (3,4)], Interaction(None, [(1,2), (3,4)], [1,2]).actions)

class PCA_Tests(unittest.TestCase):
    def test_PCA(self):        
        interactions = [
            Interaction((1,2), [1], [1]),
            Interaction((1,9), [1], [1]),
            Interaction((7,3), [1], [1])
        ]

        mem_sim = MemorySimulation(interactions)
        pca_sim = PCA().filter(mem_sim)

        self.assertEqual((1,2), mem_sim.interactions[0].context)
        self.assertEqual((1,9), mem_sim.interactions[1].context)
        self.assertEqual((7,3), mem_sim.interactions[2].context)

        self.assertNotEqual((1,2), pca_sim.interactions[0].context)
        self.assertNotEqual((1,9), pca_sim.interactions[1].context)
        self.assertNotEqual((7,3), pca_sim.interactions[2].context)

    def test_repr(self):
        self.assertEqual('"PCA"', str(PCA()))

class Sort_tests(unittest.TestCase):

    def test_sort1(self) -> None:

        interactions = [
            Interaction((7,2), [1], [1]),
            Interaction((1,9), [1], [1]),
            Interaction((8,3), [1], [1])
        ]

        mem_sim = MemorySimulation(interactions)
        srt_sim = Sort([0]).filter(mem_sim)

        self.assertEqual((7,2), mem_sim.interactions[0].context)
        self.assertEqual((1,9), mem_sim.interactions[1].context)
        self.assertEqual((8,3), mem_sim.interactions[2].context)

        self.assertEqual((1,9), srt_sim.interactions[0].context)
        self.assertEqual((7,2), srt_sim.interactions[1].context)
        self.assertEqual((8,3), srt_sim.interactions[2].context)

    def test_sort2(self) -> None:

        interactions = [
            Interaction((1,2), [1], [1]),
            Interaction((1,9), [1], [1]),
            Interaction((1,3), [1], [1])
        ]

        mem_sim = MemorySimulation(interactions)
        srt_sim = Sort([0,1]).filter(mem_sim)

        self.assertEqual((1,2), mem_sim.interactions[0].context)
        self.assertEqual((1,9), mem_sim.interactions[1].context)
        self.assertEqual((1,3), mem_sim.interactions[2].context)

        self.assertEqual((1,2), srt_sim.interactions[0].context)
        self.assertEqual((1,3), srt_sim.interactions[1].context)
        self.assertEqual((1,9), srt_sim.interactions[2].context)

    def test_sort3(self) -> None:
        interactions = [
            Interaction((1,2), [1], [1]),
            Interaction((1,9), [1], [1]),
            Interaction((1,3), [1], [1])
        ]

        mem_sim = MemorySimulation(interactions)
        srt_sim = Sort(*[0,1]).filter(mem_sim)

        self.assertEqual((1,2), mem_sim.interactions[0].context)
        self.assertEqual((1,9), mem_sim.interactions[1].context)
        self.assertEqual((1,3), mem_sim.interactions[2].context)

        self.assertEqual((1,2), srt_sim.interactions[0].context)
        self.assertEqual((1,3), srt_sim.interactions[1].context)
        self.assertEqual((1,9), srt_sim.interactions[2].context)
    
    def test_repr(self):
        self.assertEqual('{"Sort":[0]}', str(Sort([0])))
        self.assertEqual('{"Sort":[1,2]}', str(Sort([1,2])))

if __name__ == '__main__':
    unittest.main()