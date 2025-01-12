import numpy as np


class Utils:
    @staticmethod
    def get_normal_noise(seed, mean=0, std_dev=1):
        np.random.seed(seed)
        return np.random.normal(mean, std_dev)
