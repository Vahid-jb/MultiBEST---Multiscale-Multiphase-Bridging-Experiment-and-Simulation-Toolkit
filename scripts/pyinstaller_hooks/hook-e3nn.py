"""
PyInstaller hook for e3nn (equivariant neural networks).

sevenn uses e3nn for its equivariant graph neural network layers.  When
SevenNetCalculator loads a model, torch.jit.script() compiles several e3nn
functions (e.g. e3nn.math.orthonormalize) using inspect.getsource().  That
requires the .py source files to be present on disk — not only inside the PYZ
archive — so we switch to pyz+py collection mode.
"""

module_collection_mode = "pyz+py"
