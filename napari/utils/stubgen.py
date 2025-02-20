"""This module provides helper functions for autogenerating type stubs.

It is intentended to be run as a script or module as follows:

    python -m napari.utils.stubgen module.a module.b

... where `module.a` and `module.b` are the module names for which you'd
like to generate type stubs. Stubs will be written to a `.pyi` with the 
same name and directory as the input module(s).

Example
-------

    python -m napari.utils.stubgen napari.view_layers

# outputs a file to: `napari/view_layers.pyi`

Note
----
If you want to limit the objects in the module for which stubs are created,
define an __all__ = [...] attribute in the module. Otherwise, all non-private
callable methods will be stubbed.

"""
import importlib
import inspect
import sys
import textwrap
import typing
import warnings
from types import ModuleType
from typing import Any, Iterator, List, Set, Tuple, Type, Union

from typing_extensions import get_args, get_origin, get_type_hints

PYI_TEMPLATE = """
# THIS FILE IS AUTOGENERATED BY napari.utils.stubgen
# DO NOT EDIT
# flake8: noqa

from typing import *
{imports}

{body}
"""


def _format_module_str(text: str, is_pyi=False) -> str:
    """Apply black and isort formatting to text."""
    from black import FileMode, format_str
    from isort.api import sort_code_string

    text = sort_code_string(text, profile="black", float_to_top=True)
    text = format_str(text, mode=FileMode(line_length=79, is_pyi=is_pyi))
    return text.replace("NoneType", "None")


def _guess_exports(module, exclude=()) -> List[str]:
    """If __all__ wasn't provided, this function guesses what to stub."""
    return [
        k
        for k, v in vars(module).items()
        if callable(v) and not k.startswith("_") and k not in exclude
    ]


def _iter_imports(hint) -> Iterator[str]:
    """Get all imports necessary for `hint`"""
    # inspect.formatannotation strips "typing." from type annotations
    # so our signatures won't have it in there
    if not repr(hint).startswith("typing."):
        orig = get_origin(hint)
        if orig:
            yield orig.__module__

    for arg in get_args(hint):
        yield from _iter_imports(arg)

    if isinstance(hint, list):
        for i in hint:
            yield from _iter_imports(i)
    elif getattr(hint, '__module__', None) != 'builtins':
        yield hint.__module__


def generate_function_stub(func) -> Tuple[Set[str], str]:
    """Generate a stub and imports for a function."""
    sig = inspect.signature(func)

    globalns = {**getattr(func, '__globals__', {})}
    globalns.update(vars(typing))
    globalns.update(getattr(func, '_forwardrefns_', {}))

    hints = get_type_hints(func, globalns)
    sig = sig.replace(
        parameters=[
            p.replace(annotation=hints.get(p.name, p.empty))
            for p in sig.parameters.values()
        ],
        return_annotation=hints.get('return', inspect.Parameter.empty),
    )
    imports = set()
    for hint in hints.values():
        imports.update(set(_iter_imports(hint)))
    imports -= {'typing'}

    doc = f'"""{func.__doc__}"""' if func.__doc__ else '...'
    return imports, f'def {func.__name__}{sig}:\n    {doc}\n'


def _get_subclass_methods(cls: Type[Any]) -> Set[str]:
    """Return the set of method names defined (only) on a subclass."""
    all_methods = set(dir(cls))
    base_methods = (dir(base()) for base in cls.__bases__)
    return all_methods.difference(*base_methods)


def generate_class_stubs(cls) -> Tuple[Set[str], str]:
    """Generate a stub and imports for a class."""

    bases = ", ".join(f'{b.__module__}.{b.__name__}' for b in cls.__bases__)

    methods = []
    imports = set()
    for methname in sorted(_get_subclass_methods(cls)):
        method = getattr(cls, methname)
        if not callable(method):
            continue
        _imports, stub = generate_function_stub(method)
        imports.update(_imports)
        methods.append(stub)

    doc = f'"""{cls.__doc__.lstrip()}"""' if cls.__doc__ else '...'
    stub = f'class {cls.__name__}({bases}):\n    {doc}\n'
    stub += textwrap.indent("\n".join(methods), '    ')

    return imports, stub


def generate_module_stub(module: Union[str, ModuleType], save=True) -> str:
    """Generate a pyi stub for a module.

    By default saves to .pyi file with the same name as the module.
    """
    if isinstance(module, str):
        module = importlib.import_module(module)

    # try to use __all__, or guess exports
    names = getattr(module, '__all__', None)
    if not names:
        names = _guess_exports(module)
        warnings.warn(
            f'Module {module.__name__} does not provide `__all__`. '
            'Guessing exports.'
        )

    # For each object, create a stub and gather imports for the top of the file
    imports = set()
    stubs = []
    for name in names:
        obj = getattr(module, name)
        if isinstance(obj, type):
            _imports, stub = generate_class_stubs(obj)
        else:
            _imports, stub = generate_function_stub(obj)
        imports.update(_imports)
        stubs.append(stub)

    # build the final file string
    importstr = "\n".join(f'import {n}' for n in imports)
    body = '\n'.join(stubs)
    pyi = PYI_TEMPLATE.format(imports=importstr, body=body)
    # format with black and isort
    pyi = _format_module_str(pyi)

    if save:
        print("Writing stub:", module.__file__.replace(".py", ".pyi"))
        with open(module.__file__.replace(".py", ".pyi"), 'w') as f:
            f.write(pyi)

    return pyi


if __name__ == '__main__':
    import sys

    default_modules = ['napari.view_layers', 'napari.components.viewer_model']

    for mod in sys.argv[1:] or default_modules:
        generate_module_stub(mod)
