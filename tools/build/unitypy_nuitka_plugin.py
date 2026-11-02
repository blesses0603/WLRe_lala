"""Keep UnityPy's generated class table bundled without a giant C unit.

MSVC C1002 occurred compiling UnityPy 1.25.4 classes.generated with /Ox.
Nuitka's bytecode inclusion preserves the module and all class definitions;
it is not a nofollow exclusion or a runtime dependency on installed Python.
"""
from nuitka.plugins.PluginBase import NuitkaPluginBase


class UnityPyGeneratedBytecodePlugin(NuitkaPluginBase):
    plugin_name = "wlre-unitypy-generated-bytecode"
    plugin_desc = "Bundle UnityPy generated classes as bytecode to avoid MSVC C1002."

    def decideCompilation(self, module_name):
        if str(module_name) == "UnityPy.classes.generated":
            return "bytecode"
        return None
