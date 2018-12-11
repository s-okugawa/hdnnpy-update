# -*- coding: utf-8 -*-

__all__ = [
    'PREPROC',
    ]

import numpy as np
from sklearn import decomposition

from hdnnpy.utils import pprint


class PreprocBase(object):
    def __init__(self, *args, **kwargs):
        pass

    def load(self, *args, **kwargs):
        pass

    def save(self, *args, **kwargs):
        pass

    def decompose(self, *args, **kwargs):
        pass


class PCA(PreprocBase):
    def __init__(self, n_components, *args, **kwargs):
        super(PCA, self).__init__(*args, **kwargs)
        self.mean = {}
        self.components = {}

        self._n_components = n_components
        self._elements = set()

    def load(self, file_path):
        ndarray = np.load(file_path)
        self._elements = ndarray['elements'].item()
        self.mean = {element: ndarray[f'mean/{element}']
                     for element in self._elements}
        self.components = {element: ndarray[f'components/{element}']
                           for element in self._elements}

    def save(self, file_path):
        mean_dict = {f'mean/{k}': v for k, v in self.mean.items()}
        components_dict = {f'components/{k}': v
                           for k, v in self.components.items()}
        np.savez(file_path, elements=self._elements,
                 **mean_dict, **components_dict)

    def decompose(self, dataset):
        for element in set(dataset.elements) - self._elements:
            nfeature = dataset.input.shape[-1]
            indices = [i for i, e in enumerate(dataset.elemental_composition) if e == element]
            X = dataset.input.take(indices, 1).reshape(-1, nfeature)
            pca = decomposition.PCA(n_components=self._n_components)
            pca.fit(X)
            self.mean[element] = pca.mean_.astype(np.float32)
            self.components[element] = pca.components_.T.astype(np.float32)
            self._elements.add(element)
            pprint(f'Initialize PCA parameters for: {element}\n'
                   f'\tDecompose features: {nfeature} => '
                   f'{self._n_components}\n'
                   f'\tcumulative contribution rate = '
                   f'{np.sum(pca.explained_variance_ratio_)}')

        mean = np.array(
            [self.mean[element]
             for element in dataset.elemental_composition])
        components = np.array(
            [self.components[element]
             for element in dataset.elemental_composition])
        dataset.input = np.einsum(
            'ijk,jkl->ijl', dataset.input - mean, components)
        dataset.dinput = np.einsum(
            'ijkmn,jkl->ijlmn', dataset.dinput, components)


PREPROC = {None: PreprocBase, 'pca': PCA}
