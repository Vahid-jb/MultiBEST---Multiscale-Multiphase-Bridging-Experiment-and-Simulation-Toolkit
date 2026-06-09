"""
PyInstaller hook for SevenNet.

SevenNet imports TorchScript helpers during startup. Torch uses inspect.getsource()
for those helpers, which requires the SevenNet .py files to be present on disk in
frozen builds instead of only embedded in the PyInstaller PYZ archive.
"""

module_collection_mode = "pyz+py"
