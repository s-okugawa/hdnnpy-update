# coding: utf-8

import ase.build
import ase.io
import ase.neighborlist
import numpy as np


class AtomicStructure(object):
    def __init__(self, atoms):
        sorted_atoms = ase.build.sort(atoms)
        sorted_atoms.set_calculator(atoms.get_calculator())
        self._atoms = sorted_atoms
        self._cache = {}

    def __getattr__(self, item):
        return getattr(self._atoms, item)

    def __getstate__(self):
        return self._atoms

    def __len__(self):
        return len(self._atoms)

    def __setstate__(self, state):
        self._atoms = state
        self._cache = {}

    @property
    def elements(self):
        return sorted(set(self._atoms.get_chemical_symbols()))

    def clear_cache(self, cutoff_distance=None):
        if cutoff_distance:
            self._cache[cutoff_distance].clear()
        else:
            self._cache.clear()

    def get_neighbor_info(self, cutoff_distance, geometry_keys):
        ret = []
        for key in geometry_keys:
            if (cutoff_distance not in self._cache
                    or key not in self._cache[cutoff_distance]):
                if key in ['distance', 'distance_vector',
                           'j2elem', 'neigh2elem', 'neigh2j']:
                    self._calculate_distance(cutoff_distance)
                elif key in ['diff_distance']:
                    self._calculate_diff_distance(cutoff_distance)
                elif key in ['cosine']:
                    self._calculate_cosine(cutoff_distance)
                elif key in ['diff_cosine']:
                    self._calculate_diff_cosine(cutoff_distance)
            ret.append(self._cache[cutoff_distance][key])
        return zip(*ret)

    @classmethod
    def read_xyz(cls, file_path):
        return [cls(atoms) for atoms
                in ase.io.iread(str(file_path), index=':', format='xyz')]

    def _calculate_cosine(self, cutoff_distance):
        cosine = []
        for dRdr, in self.get_neighbor_info(
                cutoff_distance, ['diff_distance']):
            cosine.append(np.dot(dRdr, dRdr.T))

        self._cache[cutoff_distance].update({
            'cosine': cosine,
            })

    def _calculate_diff_cosine(self, cutoff_distance):
        diff_cosine = []
        for R, cos, dRdr in self.get_neighbor_info(
                cutoff_distance, ['distance', 'cosine', 'diff_distance']):
            dcosdr = ((dRdr[None, :, :]
                       - dRdr[:, None, :] * cos[:, :, None])
                      / R[:, None, None])
            diff_cosine.append(dcosdr)

        self._cache[cutoff_distance].update({
            'diff_cosine': diff_cosine,
            })

    def _calculate_diff_distance(self, cutoff_distance):
        diff_distance = []
        for r, R in self.get_neighbor_info(
                cutoff_distance, ['distance_vector', 'distance']):
            diff_distance.append(r / R[:, None])

        self._cache[cutoff_distance].update({
            'diff_distance': diff_distance,
            })

    def _calculate_distance(self, cutoff_distance):
        symbols = self._atoms.get_chemical_symbols()
        elements = sorted(set(symbols))
        index_element_map = [elements.index(element) for element in symbols]

        i_list, j_list, d_list, D_list = ase.neighborlist.neighbor_list(
            'ijdD', self._atoms, cutoff_distance)

        sort_indices = np.lexsort((j_list, i_list))
        i_list = i_list[sort_indices]
        j_list = j_list[sort_indices]
        d_list = d_list[sort_indices]
        D_list = D_list[sort_indices]
        elem_list = np.array([index_element_map[idx] for idx in j_list])

        i_indices = np.unique(i_list, return_index=True)[1]
        j_list = np.split(j_list, i_indices[1:])
        distance = np.split(d_list, i_indices[1:])
        distance_vector = np.split(D_list, i_indices[1:])
        elem_list = np.split(elem_list, i_indices[1:])

        j2elem = []
        neigh2elem = []
        neigh2j = []
        for j, elem in zip(j_list, elem_list):
            j2elem.append(np.unique(
                self._atoms.get_chemical_symbols(), return_index=True)[1])
            neigh2j.append(np.searchsorted(j, range(len(symbols))))
            neigh2elem.append(np.searchsorted(elem, range(len(elements))))

        self._cache[cutoff_distance] = {
            'distance': distance,
            'distance_vector': distance_vector,
            'j2elem': j2elem,
            'neigh2elem': neigh2elem,
            'neigh2j': neigh2j,
            }