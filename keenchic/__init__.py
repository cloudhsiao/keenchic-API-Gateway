import numpy as np

# Monkey patch for numpy 2.0+ compatibility
# np.int0 was removed in numpy 2.0 and replaced by np.intp
if not hasattr(np, "int0"):
    np.int0 = np.intp
