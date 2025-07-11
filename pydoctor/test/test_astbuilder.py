from __future__ import annotations

from typing import Optional, Tuple, Type, List, overload, cast
import ast

from pydoctor import astbuilder, astutils, model
from pydoctor import epydoc2stan
from pydoctor.epydoc.markup import DocstringLinker, ParsedDocstring
from pydoctor.options import Options
from pydoctor.stanutils import flatten, flatten_text
from pydoctor.epydoc.markup.epytext import Element, ParsedEpytextDocstring
from pydoctor.epydoc2stan import _get_docformat, format_summary, get_parsed_signature, get_parsed_type
from pydoctor.templatewriter.pages import format_signature
from pydoctor.test.test_packages import processPackage
from pydoctor.utils import partialclass

from . import CapSys, NotFoundLinker
import pytest

class SimpleSystem(model.System):
    """
    A system with no extensions.
    """
    extensions:List[str] = []

class ZopeInterfaceSystem(model.System):
    """
    A system with only the zope interface extension enabled.
    """
    extensions = ['pydoctor.extensions.zopeinterface']

class DeprecateSystem(model.System):
    """
    A system with only the twisted deprecated extension enabled.
    """
    extensions = ['pydoctor.extensions.deprecate']

class PydanticSystem(model.System):
    # Add our custom extension as extra
    custom_extensions = ['pydoctor.test.test_pydantic_fields']

class AttrsSystem(model.System):
    """
    A system with only the attrs extension enabled.
    """
    extensions = ['pydoctor.extensions.attrs']

systemcls_param = pytest.mark.parametrize(
    'systemcls', (model.System, # system with all extensions enalbed
                  ZopeInterfaceSystem, # system with zopeinterface extension only
                  DeprecateSystem, # system with deprecated extension only
                  SimpleSystem, # system with no extensions
                  PydanticSystem,
                  AttrsSystem,
                 )
    )

def fromText(
        text: str,
        *,
        modname: str = '<test>',
        is_package: bool = False,
        parent_name: Optional[str] = None,
        system: Optional[model.System] = None,
        systemcls: Type[model.System] = model.System
        ) -> model.Module:
    
    if system is None:
        _system = systemcls()
    else:
        _system = system
    assert _system is not None

    if parent_name is None:
        full_name = modname
    else:
        full_name = f'{parent_name}.{modname}'

    builder = _system.systemBuilder(_system)
    builder.addModuleString(text, modname, parent_name, is_package=is_package)
    builder.buildModules()
    mod = _system.allobjects[full_name]
    assert isinstance(mod, model.Module)
    return mod

def unwrap(parsed_docstring: Optional[ParsedDocstring]) -> str:
    
    if parsed_docstring is None:
        raise TypeError("parsed_docstring cannot be None")
    if not isinstance(parsed_docstring, ParsedEpytextDocstring):
        raise TypeError(f"parsed_docstring must be a ParsedEpytextDocstring instance, not {parsed_docstring.__class__.__name__}")
    epytext = parsed_docstring._tree
    assert epytext is not None
    assert epytext.tag == 'epytext'
    assert len(epytext.children) == 1
    para = epytext.children[0]
    assert isinstance(para, Element)
    assert para.tag == 'para'
    assert len(para.children) == 1
    value = para.children[0]
    assert isinstance(value, str)
    return value

def to_html(
        parsed_docstring: ParsedDocstring,
        linker: DocstringLinker = NotFoundLinker()
        ) -> str:
    return flatten(parsed_docstring.to_stan(linker))

def signature2str(func: model.Function | model.FunctionOverload, 
                  fails: bool = False) -> str:
    doc = get_parsed_signature(func)
    fromhtml = flatten_text(format_signature(func))
    if doc is not None:
        fromdocutils = doc.to_text()
        assert fromhtml == fromdocutils
    else:
        assert fails
        assert func.signature is None
    return fromhtml

@overload
def type2str(type_expr: None) -> None: ...

@overload
def type2str(type_expr: ast.expr) -> str: ...

def type2str(type_expr: Optional[ast.expr]) -> Optional[str]:
    if type_expr is None:
        return None
    else:
        from .epydoc.test_pyval_repr import color2
        return color2(type_expr)

def type2html(obj: model.Documentable) -> str:
    """
    Uses the NotFoundLinker. 
    """
    parsed_type = get_parsed_type(obj)
    assert parsed_type is not None
    return to_html(parsed_type).replace('<wbr></wbr>', '').replace('<wbr>\n</wbr>', '')

def ann_str_and_line(obj: model.Documentable) -> Tuple[str, int]:
    """Return the textual representation and line number of an object's
    type annotation.
    @param obj: Documentable object with a type annotation.
    """
    ann = obj.annotation # type: ignore[attr-defined]
    assert ann is not None
    return type2str(ann), ann.lineno

def test_node2fullname() -> None:
    """The node2fullname() function finds the full (global) name for
    a name expression in the AST.
    """

    mod = fromText('''
    class session:
        from twisted.conch.interfaces import ISession
    ''', modname='test')

    def lookup(expr: str) -> Optional[str]:
        node = ast.parse(expr, mode='eval')
        assert isinstance(node, ast.Expression)
        return astbuilder.node2fullname(node.body, mod)

    # None is returned for non-name nodes.
    assert lookup('123') is None
    # Local names are returned with their full name.
    assert lookup('session') == 'test.session'
    # A name that has no match at the top level is returned as-is.
    assert lookup('nosuchname') == 'nosuchname'
    # Unknown names are resolved as far as possible.
    assert lookup('session.nosuchname') == 'test.session.nosuchname'
    # Aliases are resolved on local names.
    assert lookup('session.ISession') == 'twisted.conch.interfaces.ISession'
    # Aliases are resolved on global names.
    assert lookup('test.session.ISession') == 'twisted.conch.interfaces.ISession'

@systemcls_param
def test_no_docstring(systemcls: Type[model.System]) -> None:
    # Inheritance of the docstring of an overridden method depends on
    # methods with no docstring having None in their 'docstring' field.
    mod = fromText('''
    def f():
        pass
    class C:
        def m(self):
            pass
    ''', modname='test', systemcls=systemcls)
    f = mod.contents['f']
    assert f.docstring is None
    m = mod.contents['C'].contents['m']
    assert m.docstring is None

@systemcls_param
def test_function_simple(systemcls: Type[model.System]) -> None:
    src = '''
    """ MOD DOC """
    def f():
        """This is a docstring."""
    '''
    mod = fromText(src, systemcls=systemcls)
    assert len(mod.contents) == 1
    func, = mod.contents.values()
    assert func.fullName() == '<test>.f'
    assert func.docstring == """This is a docstring."""
    assert isinstance(func, model.Function)
    assert func.is_async is False


@systemcls_param
def test_function_async(systemcls: Type[model.System]) -> None:
    src = '''
    """ MOD DOC """
    async def a():
        """This is a docstring."""
    '''
    mod = fromText(src, systemcls=systemcls)
    assert len(mod.contents) == 1
    func, = mod.contents.values()
    assert func.fullName() == '<test>.a'
    assert func.docstring == """This is a docstring."""
    assert isinstance(func, model.Function)
    assert func.is_async is True


@pytest.mark.parametrize('signature', (
    '()',
    '(*, a, b=None)',
    '(*, a=(), b)',
    '(a, b=3, *c, **kw)',
    '(f=True)',
    '(x=0.1, y=-2)',
    '(x, *v)',
    '(x, *, v)',
    '(x, *, v=1)',
    r"(s='theory', t='con\'text')",
    ))
@systemcls_param
def test_function_signature(signature: str, systemcls: Type[model.System]) -> None:
    """
    A round trip from source to inspect.Signature and back produces
    the original text.
    """
    mod = fromText(f'def f{signature}: ...', systemcls=systemcls)
    docfunc, = mod.contents.values()
    assert isinstance(docfunc, model.Function)
    # This little trick makes it possible to back reproduce the original signature from the genrated HTML.
    text = signature2str(docfunc)
    assert text == signature

@pytest.mark.parametrize('signature', (
    '(x, y, /)',
    '(x, y=0, /)',
    '(x, y, /, z, w)',
    '(x, y, /, z, w=42)',
    '(x, y, /, z=0, w=0)',
    '(x, y=3, /, z=5, w=7)',
    '(x, /, *v)',
    '(x, /, *, v)',
    '(x, /, *, v=1)',
    '(x, /, *v, a=1, b=2)',
    '(x, /, *, a=1, b=2, **kwargs)',
    ))
@systemcls_param
def test_function_signature_posonly(signature: str, systemcls: Type[model.System]) -> None:
    test_function_signature(signature, systemcls)


@pytest.mark.parametrize('signature', (
    '(a, a)',
    ))
@systemcls_param
def test_function_badsig(signature: str, systemcls: Type[model.System], capsys: CapSys) -> None:
    """When a function has an invalid signature, an error is logged and
    the empty signature is returned.

    Note that most bad signatures lead to a SyntaxError, which we cannot
    recover from. This test checks what happens if the AST can be produced
    but inspect.Signature() rejects the parsed parameters.
    """
    mod = fromText(f'def f{signature}: ...', systemcls=systemcls, modname='mod')
    docfunc, = mod.contents.values()
    assert isinstance(docfunc, model.Function)
    assert signature2str(docfunc, fails=True) == '(...)'
    captured = capsys.readouterr().out
    assert captured.startswith("mod:1: mod.f has invalid parameters: ")


@systemcls_param
def test_class(systemcls: Type[model.System]) -> None:
    src = '''
    class C:
        def f():
            """This is a docstring."""
    '''
    mod = fromText(src, systemcls=systemcls)
    assert len(mod.contents) == 1
    cls, = mod.contents.values()
    assert cls.fullName() == '<test>.C'
    assert cls.docstring == None
    assert len(cls.contents) == 1
    func, = cls.contents.values()
    assert func.fullName() == '<test>.C.f'
    assert func.docstring == """This is a docstring."""


@systemcls_param
def test_class_with_base(systemcls: Type[model.System]) -> None:
    src = '''
    class C:
        def f():
            """This is a docstring."""
    class D(C):
        def f():
            """This is a docstring."""
    '''
    mod = fromText(src, systemcls=systemcls)
    assert len(mod.contents) == 2
    clsC, clsD = mod.contents.values()
    assert clsC.fullName() == '<test>.C'
    assert clsC.docstring == None
    assert len(clsC.contents) == 1

    assert clsD.fullName() == '<test>.D'
    assert clsD.docstring == None
    assert len(clsD.contents) == 1

    assert isinstance(clsD, model.Class)
    assert len(clsD.bases) == 1
    base, = clsD.bases
    assert base == '<test>.C'

@systemcls_param
def test_follow_renaming(systemcls: Type[model.System]) -> None:
    src = '''
    class C: pass
    D = C
    class E(D): pass
    '''
    mod = fromText(src, systemcls=systemcls)
    C = mod.contents['C']
    E = mod.contents['E']
    assert isinstance(C, model.Class)
    assert isinstance(E, model.Class)
    assert E.baseobjects == [C], E.baseobjects

@systemcls_param
def test_relative_import_in_package(systemcls: Type[model.System]) -> None:
    """Relative imports in a package must be resolved by going up one level
    less, since we don't count "__init__.py" as a level.

    Hierarchy::

      top: def f
       - pkg: imports f and g
          - mod: def g
    """

    top_src = '''
    def f(): pass
    '''
    mod_src = '''
    def g(): pass
    '''
    pkg_src = '''
    from .. import f
    from .mod import g
    '''

    system = systemcls()
    top = fromText(top_src, modname='top', is_package=True, system=system)
    mod = fromText(mod_src, modname='top.pkg.mod', system=system)
    pkg = fromText(pkg_src, modname='pkg', parent_name='top', is_package=True,
                   system=system)

    assert pkg.resolveName('f') is top.contents['f']
    assert pkg.resolveName('g') is mod.contents['g']

@systemcls_param
@pytest.mark.parametrize('level', (1, 2, 3, 4))
def test_relative_import_past_top(
        systemcls: Type[model.System],
        level: int,
        capsys: CapSys
        ) -> None:
    """A warning is logged when a relative import goes beyond the top-level
    package.
    """
    system = systemcls()
    fromText('', modname='pkg', is_package=True, system=system)
    fromText(f'''
    from {'.' * level + 'X'} import A
    ''', modname='mod', parent_name='pkg', system=system)
    captured = capsys.readouterr().out
    if level == 1:
        assert 'relative import level' not in captured
    else:
        assert f'pkg.mod:2: relative import level ({level}) too high\n' in captured

@systemcls_param
def test_class_with_base_from_module(systemcls: Type[model.System]) -> None:
    src = '''
    from X.Y import A
    from Z import B as C
    class D(A, C):
        def f():
            """This is a docstring."""
    '''
    mod = fromText(src, systemcls=systemcls)
    assert len(mod.contents) == 1
    clsD, = mod.contents.values()

    assert clsD.fullName() == '<test>.D'
    assert clsD.docstring == None
    assert len(clsD.contents) == 1

    assert isinstance(clsD, model.Class)
    assert len(clsD.bases) == 2
    base1, base2 = clsD.bases
    assert base1 == 'X.Y.A'
    assert base2 == 'Z.B'

    src = '''
    import X
    import Y.Z as M
    class D(X.A, X.B.C, M.C):
        def f():
            """This is a docstring."""
    '''
    mod = fromText(src, systemcls=systemcls)
    assert len(mod.contents) == 1
    clsD, = mod.contents.values()

    assert clsD.fullName() == '<test>.D'
    assert clsD.docstring == None
    assert len(clsD.contents) == 1

    assert isinstance(clsD, model.Class)
    assert len(clsD.bases) == 3
    base1, base2, base3 = clsD.bases
    assert base1 == 'X.A', base1
    assert base2 == 'X.B.C', base2
    assert base3 == 'Y.Z.C', base3

@systemcls_param
def test_aliasing(systemcls: Type[model.System]) -> None:
    def addsrc(system: model.System) -> None:
        src_private = '''
        class A:
            pass
        '''
        src_export = '''
        from _private import A as B
        __all__ = ['B']
        '''
        src_user = '''
        from public import B
        class C(B):
            pass
        '''
        fromText(src_private, modname='_private', system=system)
        fromText(src_export, modname='public', system=system)
        fromText(src_user, modname='app', system=system)

    system = systemcls()
    addsrc(system)
    C = system.allobjects['app.C']
    assert isinstance(C, model.Class)
    # An older version of this test expected _private.A as the result.
    # The expected behavior was changed because:
    # - relying on on-demand processing of other modules is unreliable when
    #   there are cyclic imports: expandName() on a module that is still being
    #   processed can return the not-found result for a name that does exist
    # - code should be importing names from their official home, so if we
    #   import public.B then for the purposes of documentation public.B is
    #   the name we should use
    assert C.bases == ['public.B']

@systemcls_param
def test_more_aliasing(systemcls: Type[model.System]) -> None:
    def addsrc(system: model.System) -> None:
        src_a = '''
        class A:
            pass
        '''
        src_b = '''
        from a import A as B
        '''
        src_c = '''
        from b import B as C
        '''
        src_d = '''
        from c import C
        class D(C):
            pass
        '''
        fromText(src_a, modname='a', system=system)
        fromText(src_b, modname='b', system=system)
        fromText(src_c, modname='c', system=system)
        fromText(src_d, modname='d', system=system)

    system = systemcls()
    addsrc(system)
    D = system.allobjects['d.D']
    assert isinstance(D, model.Class)
    # An older version of this test expected a.A as the result.
    # Read the comment in test_aliasing() to learn why this was changed.
    assert D.bases == ['c.C']

@systemcls_param
def test_aliasing_recursion(systemcls: Type[model.System]) -> None:
    system = systemcls()
    src = '''
    class C:
        pass
    from mod import C
    class D(C):
        pass
    '''
    mod = fromText(src, modname='mod', system=system)
    D = mod.contents['D']
    assert isinstance(D, model.Class)
    assert D.bases == ['mod.C'], D.bases

@systemcls_param
def test_documented_no_alias(systemcls: Type[model.System]) -> None:
    """A variable that is documented should not be considered an alias."""
    # TODO: We should also verify this for inline docstrings, but the code
    #       currently doesn't support that. We should perhaps store aliases
    #       as Documentables as well, so we can change their 'kind' when
    #       an inline docstring follows the assignment.
    mod = fromText('''
    class SimpleClient:
        pass
    class Processor:
        """
        @ivar clientFactory: Callable that returns a client.
        """
        clientFactory = SimpleClient
    ''', systemcls=systemcls)
    P = mod.contents['Processor']
    f = P.contents['clientFactory']
    assert unwrap(f.parsed_docstring) == """Callable that returns a client."""
    assert f.privacyClass is model.PrivacyClass.PUBLIC
    assert f.kind is model.DocumentableKind.INSTANCE_VARIABLE
    assert f.linenumber

@systemcls_param
def test_subclasses(systemcls: Type[model.System]) -> None:
    src = '''
    class A:
        pass
    class B(A):
        pass
    '''
    system = fromText(src, systemcls=systemcls).system
    A = system.allobjects['<test>.A']
    assert isinstance(A, model.Class)
    assert A.subclasses == [system.allobjects['<test>.B']]

@systemcls_param
def test_inherit_names(systemcls: Type[model.System]) -> None:
    src = '''
    class A:
        pass
    class A(A):
        pass
    '''
    mod = fromText(src, systemcls=systemcls)
    A = mod.contents['A']
    assert isinstance(A, model.Class)
    assert [b.name for b in A.allbases()] == ['A 0']

@systemcls_param
def test_nested_class_inheriting_from_same_module(systemcls: Type[model.System]) -> None:
    src = '''
    class A:
        pass
    class B:
        class C(A):
            pass
    '''
    fromText(src, systemcls=systemcls)

@systemcls_param
def test_all_recognition(systemcls: Type[model.System]) -> None:
    """The value assigned to __all__ is parsed to Module.all."""
    mod = fromText('''
    def f():
        pass
    __all__ = ['f']
    ''', systemcls=systemcls)
    assert mod.all == ['f']
    assert '__all__' not in mod.contents

@systemcls_param
def test_docformat_recognition(systemcls: Type[model.System]) -> None:
    """The value assigned to __docformat__ is parsed to Module.docformat."""
    mod = fromText('''
    __docformat__ = 'Epytext en'

    def f():
        pass
    ''', systemcls=systemcls)
    assert mod.docformat == 'epytext'
    assert '__docformat__' not in mod.contents

@systemcls_param
def test_docformat_warn_not_str(systemcls: Type[model.System], capsys: CapSys) -> None:

    mod = fromText('''
    __docformat__ = [i for i in range(3)]

    def f():
        pass
    ''', systemcls=systemcls, modname='mod')
    captured = capsys.readouterr().out
    assert captured == 'mod:2: Cannot parse value assigned to "__docformat__": not a string\n'
    assert mod.docformat is None
    assert '__docformat__' not in mod.contents

@systemcls_param
def test_docformat_warn_not_str2(systemcls: Type[model.System], capsys: CapSys) -> None:

    mod = fromText('''
    __docformat__ = 3.14

    def f():
        pass
    ''', systemcls=systemcls, modname='mod')
    captured = capsys.readouterr().out
    assert captured == 'mod:2: Cannot parse value assigned to "__docformat__": not a string\n'
    assert mod.docformat == None
    assert '__docformat__' not in mod.contents

@systemcls_param
def test_docformat_warn_empty(systemcls: Type[model.System], capsys: CapSys) -> None:

    mod = fromText('''
    __docformat__ = '  '

    def f():
        pass
    ''', systemcls=systemcls, modname='mod')
    captured = capsys.readouterr().out
    assert captured == 'mod:2: Cannot parse value assigned to "__docformat__": empty value\n'
    assert mod.docformat == None
    assert '__docformat__' not in mod.contents

@systemcls_param
def test_docformat_warn_overrides(systemcls: Type[model.System], capsys: CapSys) -> None:
    mod = fromText('''
    __docformat__ = 'numpy'

    def f():
        pass

    __docformat__ = 'restructuredtext'
    ''', systemcls=systemcls, modname='mod')
    captured = capsys.readouterr().out
    assert captured == 'mod:7: Assignment to "__docformat__" overrides previous assignment\n'
    assert mod.docformat == 'restructuredtext'
    assert '__docformat__' not in mod.contents

@systemcls_param
def test_all_in_class_non_recognition(systemcls: Type[model.System]) -> None:
    """A class variable named __all__ is just an ordinary variable and
    does not affect Module.all.
    """
    mod = fromText('''
    class C:
        __all__ = ['f']
    ''', systemcls=systemcls)
    assert mod.all is None
    assert '__all__' not in mod.contents
    assert '__all__' in mod.contents['C'].contents

@systemcls_param
def test_all_multiple(systemcls: Type[model.System], capsys: CapSys) -> None:
    """If there are multiple assignments to __all__, a warning is logged
    and the last assignment takes effect.
    """
    mod = fromText('''
    __all__ = ['f']
    __all__ = ['g']
    ''', modname='mod', systemcls=systemcls)
    captured = capsys.readouterr().out
    assert captured == 'mod:3: Assignment to "__all__" overrides previous assignment\n'
    assert mod.all == ['g']

@systemcls_param
def test_all_bad_sequence(systemcls: Type[model.System], capsys: CapSys) -> None:
    """Values other than lists and tuples assigned to __all__ have no effect
    and a warning is logged.
    """
    mod = fromText('''
    __all__ = {}
    ''', modname='mod', systemcls=systemcls)
    captured = capsys.readouterr().out
    assert captured == 'mod:2: Cannot parse value assigned to "__all__"\n'
    assert mod.all is None

@systemcls_param
def test_all_nonliteral(systemcls: Type[model.System], capsys: CapSys) -> None:
    """Non-literals in __all__ are ignored."""
    mod = fromText('''
    __all__ = ['a', 'b', '.'.join(['x', 'y']), 'c']
    ''', modname='mod', systemcls=systemcls)
    captured = capsys.readouterr().out
    assert captured == 'mod:2: Cannot parse element 2 of "__all__"\n'
    assert mod.all == ['a', 'b', 'c']

@systemcls_param
def test_all_nonstring(systemcls: Type[model.System], capsys: CapSys) -> None:
    """Non-string literals in __all__ are ignored."""
    mod = fromText('''
    __all__ = ('a', 'b', 123, 'c', True)
    ''', modname='mod', systemcls=systemcls)
    captured = capsys.readouterr().out
    assert captured == (
        'mod:2: Element 2 of "__all__" has type "int", expected "str"\n'
        'mod:2: Element 4 of "__all__" has type "bool", expected "str"\n'
        )
    assert mod.all == ['a', 'b', 'c']

@systemcls_param
def test_all_allbad(systemcls: Type[model.System], capsys: CapSys) -> None:
    """If no value in __all__ could be parsed, the result is an empty list."""
    mod = fromText('''
    __all__ = (123, True)
    ''', modname='mod', systemcls=systemcls)
    captured = capsys.readouterr().out
    assert captured == (
        'mod:2: Element 0 of "__all__" has type "int", expected "str"\n'
        'mod:2: Element 1 of "__all__" has type "bool", expected "str"\n'
        )
    assert mod.all == []

@systemcls_param
def test_classmethod(systemcls: Type[model.System]) -> None:
    mod = fromText('''
    class C:
        @classmethod
        def f(klass):
            pass
    ''', systemcls=systemcls)
    assert mod.contents['C'].contents['f'].kind is model.DocumentableKind.CLASS_METHOD
    mod = fromText('''
    class C:
        def f(klass):
            pass
        f = classmethod(f)
    ''', systemcls=systemcls)
    assert mod.contents['C'].contents['f'].kind is model.DocumentableKind.CLASS_METHOD

@systemcls_param
def test_classdecorator(systemcls: Type[model.System]) -> None:
    mod = fromText('''
    def cd(cls):
        pass
    @cd
    class C:
        pass
    ''', modname='mod', systemcls=systemcls)
    C = mod.contents['C']
    assert isinstance(C, model.Class)
    assert C.decorators == [('mod.cd', None)]


@systemcls_param
def test_classdecorator_with_args(systemcls: Type[model.System]) -> None:
    mod = fromText('''
    def cd(): pass
    class A: pass
    @cd(A)
    class C:
        pass
    ''', modname='test', systemcls=systemcls)
    C = mod.contents['C']
    assert isinstance(C, model.Class)
    assert len(C.decorators) == 1
    (name, args), = C.decorators
    assert name == 'test.cd'
    assert args is not None
    assert len(args) == 1
    arg, = args
    assert astbuilder.node2fullname(arg, mod) == 'test.A'


@systemcls_param
def test_methoddecorator(systemcls: Type[model.System], capsys: CapSys) -> None:
    mod = fromText('''
    class C:
        def method_undecorated():
            pass

        @staticmethod
        def method_static():
            pass

        @classmethod
        def method_class(cls):
            pass

        @staticmethod
        @classmethod
        def method_both():
            pass
    ''', modname='mod', systemcls=systemcls)
    C = mod.contents['C']
    assert C.contents['method_undecorated'].kind is model.DocumentableKind.METHOD
    assert C.contents['method_static'].kind is model.DocumentableKind.STATIC_METHOD
    assert C.contents['method_class'].kind is model.DocumentableKind.CLASS_METHOD
    captured = capsys.readouterr().out
    assert captured == "mod:14: mod.C.method_both is both classmethod and staticmethod\n"


@systemcls_param
def test_assignment_to_method_in_class(systemcls: Type[model.System]) -> None:
    """An assignment to a method in a class body does not change the type
    of the documentable.

    If the name we assign to exists and it does not belong to an Attribute
    (it's a Function instead, in this test case), the assignment will be
    ignored.
    """
    mod = fromText('''
    class Base:
        def base_method():
            """Base method docstring."""

    class Sub(Base):
        base_method = wrap_method(base_method)
        """Overriding the docstring is not supported."""

        def sub_method():
            """Sub method docstring."""
        sub_method = wrap_method(sub_method)
        """Overriding the docstring is not supported."""
    ''', systemcls=systemcls)
    assert isinstance(mod.contents['Base'].contents['base_method'], model.Function)
    assert mod.contents['Sub'].contents.get('base_method') is None
    sub_method = mod.contents['Sub'].contents['sub_method']
    assert isinstance(sub_method, model.Function)
    assert sub_method.docstring == """Sub method docstring."""


@systemcls_param
def test_assignment_to_method_in_init(systemcls: Type[model.System]) -> None:
    """An assignment to a method inside __init__() does not change the type
    of the documentable.

    If the name we assign to exists and it does not belong to an Attribute
    (it's a Function instead, in this test case), the assignment will be
    ignored.
    """
    mod = fromText('''
    class Base:
        def base_method():
            """Base method docstring."""

    class Sub(Base):
        def sub_method():
            """Sub method docstring."""

        def __init__(self):
            self.base_method = wrap_method(self.base_method)
            """Overriding the docstring is not supported."""
            self.sub_method = wrap_method(self.sub_method)
            """Overriding the docstring is not supported."""
    ''', systemcls=systemcls)
    assert isinstance(mod.contents['Base'].contents['base_method'], model.Function)
    assert mod.contents['Sub'].contents.get('base_method') is None
    sub_method = mod.contents['Sub'].contents['sub_method']
    assert isinstance(sub_method, model.Function)
    assert sub_method.docstring == """Sub method docstring."""


@systemcls_param
def test_import_star(systemcls: Type[model.System]) -> None:
    mod_a = fromText('''
    def f(): pass
    ''', modname='a', systemcls=systemcls)
    mod_b = fromText('''
    from a import *
    ''', modname='b', system=mod_a.system)
    assert mod_b.resolveName('f') == mod_a.contents['f']


@systemcls_param
def test_import_func_from_package(systemcls: Type[model.System]) -> None:
    """Importing a function from a package should look in the C{__init__}
    module.

    In this test the following hierarchy is constructed::

        package a
          module __init__
            defines function 'f'
          module c
            imports function 'f'
        module b
          imports function 'f'

    We verify that when module C{b} and C{c} import the name C{f} from
    package C{a}, they import the function C{f} from the module C{a.__init__}.
    """
    system = systemcls()
    mod_a = fromText('''
    def f(): pass
    ''', modname='a', is_package=True, system=system)
    mod_b = fromText('''
    from a import f
    ''', modname='b', system=system)
    mod_c = fromText('''
    from . import f
    ''', modname='c', parent_name='a', system=system)
    assert mod_b.resolveName('f') == mod_a.contents['f']
    assert mod_c.resolveName('f') == mod_a.contents['f']


@systemcls_param
def test_import_module_from_package(systemcls: Type[model.System]) -> None:
    """Importing a module from a package should not look in C{__init__}
    module.

    In this test the following hierarchy is constructed::

        package a
          module __init__
          module b
            defines function 'f'
        module c
          imports module 'a.b'

    We verify that when module C{c} imports the name C{b} from package C{a},
    it imports the module C{a.b} which contains C{f}.
    """
    system = systemcls()
    fromText('''
    # This module intentionally left blank.
    ''', modname='a', system=system, is_package=True)
    mod_b = fromText('''
    def f(): pass
    ''', modname='b', parent_name='a', system=system)
    mod_c = fromText('''
    from a import b
    f = b.f
    ''', modname='c', system=system)
    assert mod_c.resolveName('f') == mod_b.contents['f']


@systemcls_param
def test_inline_docstring_modulevar(systemcls: Type[model.System]) -> None:
    mod = fromText('''
    """regular module docstring

    @var b: doc for b
    """

    """not a docstring"""

    a = 1
    """inline doc for a"""

    b = 2

    def f():
        pass
    """not a docstring"""
    ''', modname='test', systemcls=systemcls)
    assert sorted(mod.contents.keys()) == ['a', 'b', 'f']
    a = mod.contents['a']
    assert a.docstring == """inline doc for a"""
    b = mod.contents['b']
    assert unwrap(b.parsed_docstring) == """doc for b"""
    f = mod.contents['f']
    assert not f.docstring

@systemcls_param
def test_inline_docstring_classvar(systemcls: Type[model.System]) -> None:
    mod = fromText('''
    class C:
        """regular class docstring"""

        def f(self):
            pass
        """not a docstring"""

        a = 1
        """inline doc for a"""

        """not a docstring"""

        _b = 2
        """inline doc for _b"""

        None
        """not a docstring"""
    ''', modname='test', systemcls=systemcls)
    C = mod.contents['C']
    assert sorted(C.contents.keys()) == ['_b', 'a', 'f']
    f = C.contents['f']
    assert not f.docstring
    a = C.contents['a']
    assert a.docstring == """inline doc for a"""
    assert a.privacyClass is model.PrivacyClass.PUBLIC
    b = C.contents['_b']
    assert b.docstring == """inline doc for _b"""
    assert b.privacyClass is model.PrivacyClass.PRIVATE

@systemcls_param
def test_inline_docstring_annotated_classvar(systemcls: Type[model.System]) -> None:
    mod = fromText('''
    class C:
        """regular class docstring"""

        a: int
        """inline doc for a"""

        _b: int = 4
        """inline doc for _b"""
    ''', modname='test', systemcls=systemcls)
    C = mod.contents['C']
    assert sorted(C.contents.keys()) == ['_b', 'a']
    a = C.contents['a']
    assert a.docstring == """inline doc for a"""
    assert a.privacyClass is model.PrivacyClass.PUBLIC
    b = C.contents['_b']
    assert b.docstring == """inline doc for _b"""
    assert b.privacyClass is model.PrivacyClass.PRIVATE

@systemcls_param
def test_inline_docstring_instancevar(systemcls: Type[model.System]) -> None:
    mod = fromText('''
    class C:
        """regular class docstring"""

        d = None
        """inline doc for d"""

        f = None
        """inline doc for f"""

        def __init__(self):
            self.a = 1
            """inline doc for a"""

            """not a docstring"""

            self._b = 2
            """inline doc for _b"""

            x = -1
            """not a docstring"""

            self.c = 3
            """inline doc for c"""

            self.d = 4

            self.e = 5
        """not a docstring"""

        def set_f(self, value):
            self.f = value
    ''', modname='test', systemcls=systemcls)
    C = mod.contents['C']
    assert sorted(C.contents.keys()) == [
        '__init__', '_b', 'a', 'c', 'd', 'e', 'f', 'set_f'
        ]
    a = C.contents['a']
    assert a.docstring == """inline doc for a"""
    assert a.privacyClass is model.PrivacyClass.PUBLIC
    assert a.kind is model.DocumentableKind.INSTANCE_VARIABLE
    b = C.contents['_b']
    assert b.docstring == """inline doc for _b"""
    assert b.privacyClass is model.PrivacyClass.PRIVATE
    assert b.kind is model.DocumentableKind.INSTANCE_VARIABLE
    c = C.contents['c']
    assert c.docstring == """inline doc for c"""
    assert c.privacyClass is model.PrivacyClass.PUBLIC
    assert c.kind is model.DocumentableKind.INSTANCE_VARIABLE
    d = C.contents['d']
    assert d.docstring == """inline doc for d"""
    assert d.privacyClass is model.PrivacyClass.PUBLIC
    assert d.kind is model.DocumentableKind.INSTANCE_VARIABLE
    e = C.contents['e']
    assert not e.docstring
    f = C.contents['f']
    assert f.docstring == """inline doc for f"""
    assert f.privacyClass is model.PrivacyClass.PUBLIC
    assert f.kind is model.DocumentableKind.INSTANCE_VARIABLE

@systemcls_param
def test_inline_docstring_annotated_instancevar(systemcls: Type[model.System]) -> None:
    mod = fromText('''
    class C:
        """regular class docstring"""

        a: int

        def __init__(self):
            self.a = 1
            """inline doc for a"""

            self.b: int = 2
            """inline doc for b"""
    ''', modname='test', systemcls=systemcls)
    C = mod.contents['C']
    assert sorted(C.contents.keys()) == ['__init__', 'a', 'b']
    a = C.contents['a']
    assert a.docstring == """inline doc for a"""
    b = C.contents['b']
    assert b.docstring == """inline doc for b"""

@systemcls_param
def test_docstring_assignment(systemcls: Type[model.System], capsys: CapSys) -> None:
    mod = fromText(r'''
    def fun():
        pass

    class CLS:

        def method1():
            """Temp docstring."""
            pass

        def method2():
            pass

        method1.__doc__ = "Override docstring #1"

    fun.__doc__ = "Happy Happy Joy Joy"
    CLS.__doc__ = "Clears the screen"
    CLS.method2.__doc__ = "Set docstring #2"

    None.__doc__ = "Free lunch!"
    real.__doc__ = "Second breakfast"
    fun.__doc__ = codecs.encode('Pnrfne fnynq', 'rot13')
    CLS.method1.__doc__ = 4

    def mark_unavailable(func):
        # No warning: docstring updates in functions are ignored.
        func.__doc__ = func.__doc__ + '\n\nUnavailable on this system.'
    ''', systemcls=systemcls)
    fun = mod.contents['fun']
    assert fun.kind is model.DocumentableKind.FUNCTION
    assert fun.docstring == """Happy Happy Joy Joy"""
    CLS = mod.contents['CLS']
    assert CLS.kind is model.DocumentableKind.CLASS
    assert CLS.docstring == """Clears the screen"""
    method1 = CLS.contents['method1']
    assert method1.kind is model.DocumentableKind.METHOD
    assert method1.docstring == "Override docstring #1"
    method2 = CLS.contents['method2']
    assert method2.kind is model.DocumentableKind.METHOD
    assert method2.docstring == "Set docstring #2"
    captured = capsys.readouterr()
    assert captured.out == (
        '<test>:14: Existing docstring at line 8 is overriden\n'
        '<test>:20: Unable to figure out target for __doc__ assignment\n'
        '<test>:21: Unable to figure out target for __doc__ assignment: computed full name not found: real\n'
        '<test>:22: Unable to figure out value for __doc__ assignment, maybe too complex\n'
        '<test>:23: Ignoring value assigned to __doc__: not a string\n'
    )
    
@systemcls_param
def test_docstring_assignment_detuple(systemcls: Type[model.System], capsys: CapSys) -> None:
    """We currently don't trace values for detupling assignments, so when
    assigning to __doc__ we get a warning about the unknown value.
    """
    fromText('''
    def fun():
        pass

    fun.__doc__, other = 'Detupling to __doc__', 'is not supported'
    ''', modname='test', systemcls=systemcls)
    captured = capsys.readouterr().out
    assert captured == (
        "test:5: Unable to figure out value for __doc__ assignment, maybe too complex\n"
        )

@systemcls_param
def test_variable_scopes(systemcls: Type[model.System]) -> None:
    mod = fromText('''
    l = 1
    """module-level l"""

    m = 1
    """module-level m"""

    class C:
        """class docstring

        @ivar k: class level doc for k
        """

        a = None

        k = 640

        m = 2
        """class-level m"""

        def __init__(self):
            self.a = 1
            """inline doc for a"""
            self.l = 2
            """instance l"""
    ''', modname='test', systemcls=systemcls)
    l1 = mod.contents['l']
    assert l1.kind is model.DocumentableKind.VARIABLE
    assert l1.docstring == """module-level l"""
    m1 = mod.contents['m']
    assert m1.kind is model.DocumentableKind.VARIABLE
    assert m1.docstring == """module-level m"""
    C = mod.contents['C']
    assert sorted(C.contents.keys()) == ['__init__', 'a', 'k', 'l', 'm']
    a = C.contents['a']
    assert a.kind is model.DocumentableKind.INSTANCE_VARIABLE
    assert a.docstring == """inline doc for a"""
    k = C.contents['k']
    assert k.kind is model.DocumentableKind.INSTANCE_VARIABLE
    assert unwrap(k.parsed_docstring) == """class level doc for k"""
    l2 = C.contents['l']
    assert l2.kind is model.DocumentableKind.INSTANCE_VARIABLE
    assert l2.docstring == """instance l"""
    m2 = C.contents['m']
    assert m2.kind is model.DocumentableKind.CLASS_VARIABLE
    assert m2.docstring == """class-level m"""

@systemcls_param
def test_variable_types(systemcls: Type[model.System]) -> None:
    mod = fromText('''
    class C:
        """class docstring

        @cvar a: first
        @type a: string

        @type b: string
        @cvar b: second

        @type c: string

        @ivar d: fourth
        @type d: string

        @type e: string
        @ivar e: fifth

        @type f: string

        @type g: string
        """

        a = "A"

        b = "B"

        c = "C"
        """third"""

        def __init__(self):

            self.d = "D"

            self.e = "E"

            self.f = "F"
            """sixth"""

            self.g = g = "G"
            """seventh"""
    ''', modname='test', systemcls=systemcls)
    C = mod.contents['C']
    assert sorted(C.contents.keys()) == [
        '__init__', 'a', 'b', 'c', 'd', 'e', 'f', 'g'
        ]
    a = C.contents['a']
    assert unwrap(a.parsed_docstring) == """first"""
    assert str(unwrap(a.parsed_type)) == 'string'
    assert a.kind is model.DocumentableKind.CLASS_VARIABLE
    b = C.contents['b']
    assert unwrap(b.parsed_docstring) == """second"""
    assert str(unwrap(b.parsed_type)) == 'string'
    assert b.kind is model.DocumentableKind.CLASS_VARIABLE
    c = C.contents['c']
    assert c.docstring == """third"""
    assert str(unwrap(c.parsed_type)) == 'string'
    assert c.kind is model.DocumentableKind.CLASS_VARIABLE
    d = C.contents['d']
    assert unwrap(d.parsed_docstring) == """fourth"""
    assert str(unwrap(d.parsed_type)) == 'string'
    assert d.kind is model.DocumentableKind.INSTANCE_VARIABLE
    e = C.contents['e']
    assert unwrap(e.parsed_docstring) == """fifth"""
    assert str(unwrap(e.parsed_type)) == 'string'
    assert e.kind is model.DocumentableKind.INSTANCE_VARIABLE
    f = C.contents['f']
    assert f.docstring == """sixth"""
    assert str(unwrap(f.parsed_type)) == 'string'
    assert f.kind is model.DocumentableKind.INSTANCE_VARIABLE
    g = C.contents['g']
    assert g.docstring == """seventh"""
    assert str(unwrap(g.parsed_type)) == 'string'
    assert g.kind is model.DocumentableKind.INSTANCE_VARIABLE

@systemcls_param
def test_annotated_variables(systemcls: Type[model.System]) -> None:
    mod = fromText('''
    class C:
        """class docstring

        @cvar a: first
        @type a: string

        @type b: string
        @cvar b: second
        """

        a: str = "A"

        b: str

        c: str = "C"
        """third"""

        d: str
        """fourth"""

        e: List['C']
        """fifth"""

        f: 'List[C]'
        """sixth"""

        g: 'List["C"]'
        """seventh"""

        def __init__(self):
            self.s: List[str] = []
            """instance"""

    m: bytes = b"M"
    """module-level"""
    ''', modname='test', systemcls=systemcls)

    C = mod.contents['C']
    a = C.contents['a']
    assert unwrap(a.parsed_docstring) == """first"""
    assert type2html(a) == 'string'
    b = C.contents['b']
    assert unwrap(b.parsed_docstring) == """second"""
    assert type2html(b) == 'string'
    c = C.contents['c']
    assert c.docstring == """third"""
    assert type2html(c) == '<code><a>str</a></code>'
    d = C.contents['d']
    assert d.docstring == """fourth"""
    assert type2html(d) == '<code><a>str</a></code>'
    e = C.contents['e']
    assert e.docstring == """fifth"""
    assert type2html(e) == '<code><a>List</a>[<a>C</a>]</code>'
    f = C.contents['f']
    assert f.docstring == """sixth"""
    assert type2html(f) == '<code><a>List</a>[<a>C</a>]</code>'
    g = C.contents['g']
    assert g.docstring == """seventh"""
    assert type2html(g) == '<code><a>List</a>[<a>C</a>]</code>'
    s = C.contents['s']
    assert s.docstring == """instance"""
    assert type2html(s) == '<code><a>List</a>[<a>str</a>]</code>'
    m = mod.contents['m']
    assert m.docstring == """module-level"""
    assert type2html(m) == '<code><a>bytes</a></code>'

@systemcls_param
def test_type_comment(systemcls: Type[model.System], capsys: CapSys) -> None:
    mod = fromText('''
    d = {} # type: dict[str, int]
    i = [] # type: ignore[misc]
    ''', systemcls=systemcls)
    assert type2str(cast(model.Attribute, mod.contents['d']).annotation) == 'dict[str, int]'
    # We don't use ignore comments for anything at the moment,
    # but do verify that their presence doesn't break things.
    assert type2str(cast(model.Attribute, mod.contents['i']).annotation) == 'list'
    assert not capsys.readouterr().out

@systemcls_param
def test_unstring_annotation(systemcls: Type[model.System]) -> None:
    """Annotations or parts thereof that are strings are parsed and
    line number information is preserved.
    """
    mod = fromText('''
    a: "int"
    b: 'str' = 'B'
    c: list["Thingy"]
    ''', systemcls=systemcls)
    assert ann_str_and_line(mod.contents['a']) == ('int', 2)
    assert ann_str_and_line(mod.contents['b']) == ('str', 3)
    assert ann_str_and_line(mod.contents['c']) == ('list[Thingy]', 4)

@systemcls_param
def test_upgrade_annotation(systemcls: Type[model.System]) -> None:
    """Annotations using old style Unions or Optionals are upgraded to python 3.10+ style. 
    Deprecated aliases like List, Tuple Dict are also translated to their built ins versions.
    """
    mod = fromText('''\
    from typing import Union, Optional, List
    a: Union[str, int]
    b: Optional[str]
    c: List[B]
    d: Optional[Union[str, int, bytes]]
    e: Union[str]
    f: Union[(str,)]
    g: Optional[1, 2] # wrong, so we don't process it
    h: Union[list[str]]
  
    class List:
        Union: Union[a, b]
    ''', systemcls=systemcls)
    assert ann_str_and_line(mod.contents['a']) == ('str | int', 2)
    assert ann_str_and_line(mod.contents['b']) == ('str | None', 3)
    assert ann_str_and_line(mod.contents['c']) == ('list[B]', 4)
    assert ann_str_and_line(mod.contents['d']) == ('str | int | bytes | None', 5)
    assert ann_str_and_line(mod.contents['e']) == ('str', 6)
    assert ann_str_and_line(mod.contents['f']) == ('str', 7)
    assert ann_str_and_line(mod.contents['g']) == ('Optional[1, 2]', 8)
    assert ann_str_and_line(mod.contents['h']) == ('list[str]', 9)
    assert ann_str_and_line(mod.contents['List'].contents['Union']) == ('a | b', 12)

@pytest.mark.parametrize('annotation', ("[", "pass", "1 ; 2"))
@systemcls_param
def test_bad_string_annotation(
        annotation: str, systemcls: Type[model.System], capsys: CapSys
        ) -> None:
    """Invalid string annotations must be reported as syntax errors."""
    mod = fromText(f'''
    x: "{annotation}"
    ''', modname='test', systemcls=systemcls)
    assert isinstance(cast(model.Attribute, mod.contents['x']).annotation, ast.expr)
    assert "syntax error in annotation" in capsys.readouterr().out

@pytest.mark.parametrize('annotation,expected', (
    ("Literal['[', ']']", "Literal['[', ']']"),
    ("typing.Literal['pass', 'raise']", "typing.Literal['pass', 'raise']"),
    ("Optional[Literal['1 ; 2']]", "Optional[Literal['1 ; 2']]"),
    ("'Literal'['!']", "Literal['!']"),
    (r"'Literal[\'if\', \'while\']'", "Literal['if', 'while']"),
    ))
def test_literal_string_annotation(annotation: str, expected: str) -> None:
    """Strings inside Literal annotations must not be recursively parsed."""
    stmt, = ast.parse(annotation).body
    assert isinstance(stmt, ast.Expr)
    unstringed = astutils._AnnotationStringParser().visit(stmt.value)
    assert astutils.unparse(unstringed).strip() == expected

@systemcls_param
def test_inferred_variable_types(systemcls: Type[model.System]) -> None:
    mod = fromText('''
    class C:
        a = "A"
        b = 2
        c = ['a', 'b', 'c']
        d = {'a': 1, 'b': 2}
        e = (True, False, True)
        f = 1.618
        g = {2, 7, 1, 8}
        h = []
        i = ['r', 2, 'd', 2]
        j = ((), ((), ()))
        n = None
        x = list(range(10))
        y = [n for n in range(10) if n % 2]
        def __init__(self):
            self.s = ['S']
            self.t = t = 'T'
    m = b'octets'
    ''', modname='test', systemcls=systemcls)
    C = mod.contents['C']
    assert ann_str_and_line(C.contents['a']) == ('str', 3)
    assert ann_str_and_line(C.contents['b']) == ('int', 4)
    assert ann_str_and_line(C.contents['c']) == ('list[str]', 5)
    assert ann_str_and_line(C.contents['d']) == ('dict[str, int]', 6)
    assert ann_str_and_line(C.contents['e']) == ('tuple[bool, ...]', 7)
    assert ann_str_and_line(C.contents['f']) == ('float', 8)
    assert ann_str_and_line(C.contents['g']) == ('set[int]', 9)
    # Element type is unknown, not uniform or too complex.
    assert ann_str_and_line(C.contents['h']) == ('list', 10)
    assert ann_str_and_line(C.contents['i']) == ('list', 11)
    assert ann_str_and_line(C.contents['j']) == ('tuple', 12)
    # It is unlikely that a variable actually will contain only None,
    # so we should treat this as not be able to infer the type.
    assert cast(model.Attribute, C.contents['n']).annotation is None
    # These expressions are considered too complex for pydoctor.
    # Maybe we can use an external type inferrer at some point.
    assert cast(model.Attribute, C.contents['x']).annotation is None
    assert cast(model.Attribute, C.contents['y']).annotation is None
    # Type inference isn't different for module and instance variables,
    # so we don't need to re-test everything.
    assert ann_str_and_line(C.contents['s']) == ('list[str]', 17)
    # Check that type is inferred on assignments with multiple targets.
    assert ann_str_and_line(C.contents['t']) == ('str', 18)
    assert ann_str_and_line(mod.contents['m']) == ('bytes', 19)

@systemcls_param
def test_detupling_assignment(systemcls: Type[model.System]) -> None:
    mod = fromText('''
    a, b, c = range(3)
    ''', modname='test', systemcls=systemcls)
    assert sorted(mod.contents.keys()) == ['a', 'b', 'c']

@systemcls_param
def test_property_decorator(systemcls: Type[model.System]) -> None:
    """A function decorated with '@property' is documented as an attribute."""
    mod = fromText('''
    class C:
        @property
        def prop(self) -> str:
            """For sale."""
            return 'seaside'
        @property
        def oldschool(self):
            """
            @return: For rent.
            @rtype: string
            @see: U{https://example.com/}
            """
            return 'downtown'
    ''', modname='test', systemcls=systemcls)
    C = mod.contents['C']

    prop = C.contents['prop']
    assert isinstance(prop, model.Attribute)
    assert prop.kind is model.DocumentableKind.PROPERTY
    assert prop.docstring == """For sale."""
    assert type2str(prop.annotation) == 'str'

    oldschool = C.contents['oldschool']
    assert isinstance(oldschool, model.Attribute)
    assert oldschool.kind is model.DocumentableKind.PROPERTY
    assert isinstance(oldschool.parsed_docstring, ParsedEpytextDocstring)
    assert unwrap(oldschool.parsed_docstring) == """For rent."""
    assert flatten(format_summary(oldschool)) == 'For rent.'
    assert isinstance(oldschool.parsed_type, ParsedEpytextDocstring)
    assert str(unwrap(oldschool.parsed_type)) == 'string'
    fields = oldschool.parsed_docstring.fields
    assert len(fields) == 1
    assert fields[0].tag() == 'see'


@systemcls_param
def test_property_setter(systemcls: Type[model.System], capsys: CapSys) -> None:
    """Property setter and deleter methods are renamed, so they don't replace
    the property itself.
    """
    mod = fromText('''
    class C:
        @property
        def prop(self):
            """Getter."""
        @prop.setter
        def prop(self, value):
            """Setter."""
        @prop.deleter
        def prop(self):
            """Deleter."""
    ''', modname='mod', systemcls=systemcls)
    C = mod.contents['C']

    getter = C.contents['prop']
    assert isinstance(getter, model.Attribute)
    assert getter.kind is model.DocumentableKind.PROPERTY
    assert getter.docstring == """Getter."""

    setter = C.contents['prop.setter']
    assert isinstance(setter, model.Function)
    assert setter.kind is model.DocumentableKind.METHOD
    assert setter.docstring == """Setter."""

    deleter = C.contents['prop.deleter']
    assert isinstance(deleter, model.Function)
    assert deleter.kind is model.DocumentableKind.METHOD
    assert deleter.docstring == """Deleter."""


@systemcls_param
def test_property_custom(systemcls: Type[model.System], capsys: CapSys) -> None:
    """Any custom decorator with a name ending in 'property' makes a method
    into a property getter.
    """
    mod = fromText('''
    class C:
        @deprecate.deprecatedProperty(incremental.Version("Twisted", 18, 7, 0))
        def processes(self):
            return {}
        @async_property
        async def remote_value(self):
            return await get_remote_value()
        @abc.abstractproperty
        def name(self):
            raise NotImplementedError
    ''', modname='mod', systemcls=systemcls)
    C = mod.contents['C']

    deprecated = C.contents['processes']
    assert isinstance(deprecated, model.Attribute)
    assert deprecated.kind is model.DocumentableKind.PROPERTY

    async_prop = C.contents['remote_value']
    assert isinstance(async_prop, model.Attribute)
    assert async_prop.kind is model.DocumentableKind.PROPERTY

    abstract_prop = C.contents['name']
    assert isinstance(abstract_prop, model.Attribute)
    assert abstract_prop.kind is model.DocumentableKind.PROPERTY


@pytest.mark.parametrize('decoration', ('classmethod', 'staticmethod'))
@systemcls_param
def test_property_conflict(
        decoration: str, systemcls: Type[model.System], capsys: CapSys
        ) -> None:
    """Warn when a method is decorated as both property and class/staticmethod.
    These decoration combinations do not create class/static properties.
    """
    mod = fromText(f'''
    class C:
        @{decoration}
        @property
        def prop():
            raise NotImplementedError
    ''', modname='mod', systemcls=systemcls)
    C = mod.contents['C']
    assert C.contents['prop'].kind is model.DocumentableKind.PROPERTY
    captured = capsys.readouterr().out
    assert captured == f"mod:3: mod.C.prop is both property and {decoration}\n"

@systemcls_param
def test_ignore_function_contents(systemcls: Type[model.System]) -> None:
    mod = fromText('''
    def outer():
        """Outer function."""

        class Clazz:
            """Inner class."""

        def func():
            """Inner function."""

        var = 1
        """Local variable."""
    ''', systemcls=systemcls)
    outer = mod.contents['outer']
    assert not outer.contents

@systemcls_param
def test_overload(systemcls: Type[model.System], capsys: CapSys) -> None:
    # Confirm decorators retained on overloads, docstring ignored for overloads,
    # and that overloads after the primary function are skipped
    mod = fromText("""
        from typing import overload
        def dec(fn):
            pass
        @dec
        @overload
        def parse(s:str)->str:
            ...
        @overload
        def parse(s:bytes)->bytes:
            '''Ignored docstring'''
            ...
        def parse(s:Union[str, bytes])->Union[str, bytes]:
            pass
        @overload
        def parse(s:str)->bytes:
            ...
        """, systemcls=systemcls)
    func = mod.contents['parse']
    assert isinstance(func, model.Function)
    assert signature2str(func) == '(s: Union[str, bytes]) -> Union[str, bytes]'
    assert [astbuilder.node2dottedname(d) for d in (func.decorators or ())] == []
    assert len(func.overloads) == 2
    assert [astbuilder.node2dottedname(d) for d in func.overloads[0].decorators] == [['dec'], ['overload']]
    assert [astbuilder.node2dottedname(d) for d in func.overloads[1].decorators] == [['overload']]
    assert signature2str(func.overloads[0]) == '(s: str) -> str'
    assert signature2str(func.overloads[1]) == '(s: bytes) -> bytes'
    assert capsys.readouterr().out.splitlines() == [
        '<test>:11: <test>.parse overload has docstring, unsupported',
        '<test>:15: <test>.parse overload appeared after primary function',
    ]

@systemcls_param
def test_constant_module(systemcls: Type[model.System]) -> None:
    """
    Module variables with all-uppercase names are recognized as constants.
    """
    mod = fromText('''
    LANG = 'FR'
    ''', systemcls=systemcls)
    lang = mod.contents['LANG']
    assert isinstance(lang, model.Attribute)
    assert lang.kind is model.DocumentableKind.CONSTANT
    assert ast.literal_eval(getattr(mod.resolveName('LANG'), 'value')) == 'FR'

@systemcls_param
def test_constant_module_with_final(systemcls: Type[model.System]) -> None:
    """
    Module variables annotated with typing.Final are recognized as constants.
    """
    mod = fromText('''
    from typing import Final
    lang: Final = 'fr'
    ''', systemcls=systemcls)
    attr = mod.resolveName('lang')
    assert isinstance(attr, model.Attribute)
    assert attr.kind == model.DocumentableKind.CONSTANT
    assert attr.value is not None
    assert ast.literal_eval(attr.value) == 'fr'

@systemcls_param
def test_constant_module_with_typing_extensions_final(systemcls: Type[model.System]) -> None:
    """
    Module variables annotated with typing_extensions.Final are recognized as constants.
    """
    mod = fromText('''
    from typing_extensions import Final
    lang: Final = 'fr'
    ''', systemcls=systemcls)
    attr = mod.resolveName('lang')
    assert isinstance(attr, model.Attribute)
    assert attr.kind == model.DocumentableKind.CONSTANT
    assert attr.value is not None
    assert ast.literal_eval(attr.value) == 'fr'

@systemcls_param
def test_constant_module_with_final_subscript1(systemcls: Type[model.System]) -> None:
    """
    It can recognize constants defined with typing.Final[something]
    """
    mod = fromText('''
    from typing import Final
    lang: Final[Sequence[str]] = ('fr', 'en')
    ''', systemcls=systemcls)
    attr = mod.resolveName('lang')
    assert isinstance(attr, model.Attribute)
    assert attr.kind == model.DocumentableKind.CONSTANT
    assert attr.value is not None
    assert ast.literal_eval(attr.value) == ('fr', 'en')
    assert attr.annotation
    assert astutils.unparse(attr.annotation).strip() == "Sequence[str]"

@systemcls_param
def test_constant_module_with_final_subscript2(systemcls: Type[model.System]) -> None:
    """
    It can recognize constants defined with typing.Final[something]. 
    And it automatically remove the Final part from the annotation.
    """
    mod = fromText('''
    import typing
    lang: typing.Final[tuple] = ('fr', 'en')
    ''', systemcls=systemcls)
    attr = mod.resolveName('lang')
    assert isinstance(attr, model.Attribute)
    assert attr.kind == model.DocumentableKind.CONSTANT
    assert attr.value is not None
    assert ast.literal_eval(attr.value) == ('fr', 'en')
    assert astbuilder.node2fullname(attr.annotation, attr) == "tuple"

@systemcls_param
def test_constant_module_with_final_subscript_invalid_warns(systemcls: Type[model.System], capsys: CapSys) -> None:
    """
    It warns if there is an invalid Final annotation.
    """
    mod = fromText('''
    from typing import Final
    lang: Final[tuple, 12:13] = ('fr', 'en')
    ''', systemcls=systemcls, modname='mod')
    attr = mod.resolveName('lang')
    assert isinstance(attr, model.Attribute)
    assert attr.kind == model.DocumentableKind.CONSTANT
    assert attr.value is not None
    assert ast.literal_eval(attr.value) == ('fr', 'en')
    
    captured = capsys.readouterr().out
    assert "mod:3: Annotation is invalid, it should not contain slices.\n" == captured
    assert attr.annotation
    assert astutils.unparse(attr.annotation).strip() == "tuple[str, ...]"

@systemcls_param
def test_constant_module_with_final_subscript_invalid_warns2(systemcls: Type[model.System], capsys: CapSys) -> None:
    """
    It warns if there is an invalid Final annotation.
    """
    mod = fromText('''
    import typing
    lang: typing.Final[12:13] = ('fr', 'en')
    ''', systemcls=systemcls, modname='mod')
    attr = mod.resolveName('lang')
    assert isinstance(attr, model.Attribute)
    assert attr.kind == model.DocumentableKind.CONSTANT
    assert attr.value is not None
    assert ast.literal_eval(attr.value) == ('fr', 'en')
    
    captured = capsys.readouterr().out
    assert "mod:3: Annotation is invalid, it should not contain slices.\n" == captured
    assert attr.annotation
    assert astutils.unparse(attr.annotation).strip() == "tuple[str, ...]"

@systemcls_param
def test_constant_module_with_final_annotation_gets_infered(systemcls: Type[model.System]) -> None:
    """
    It can recognize constants defined with typing.Final. 
    It will infer the type of the constant if Final do not use subscripts.
    """
    mod = fromText('''
    import typing
    lang: typing.Final = 'fr'
    ''', systemcls=systemcls)
    attr = mod.resolveName('lang')
    assert isinstance(attr, model.Attribute)
    assert attr.kind == model.DocumentableKind.CONSTANT
    assert attr.value is not None
    assert ast.literal_eval(attr.value) == 'fr'
    assert astbuilder.node2fullname(attr.annotation, attr) == "str"

@systemcls_param
def test_constant_class(systemcls: Type[model.System]) -> None:
    """
    Class variables with all-uppercase names are recognized as constants.
    """
    mod = fromText('''
    class Clazz:
        """Class."""
        LANG = 'FR'
    ''', systemcls=systemcls)
    attr = mod.resolveName('Clazz.LANG')
    assert isinstance(attr, model.Attribute)
    assert attr.kind == model.DocumentableKind.CONSTANT
    assert attr.value is not None
    assert ast.literal_eval(attr.value) == 'FR'


@systemcls_param
def test_all_caps_variable_in_instance_is_not_a_constant(systemcls: Type[model.System], capsys: CapSys) -> None:
    """
    Currently, it does not mark instance members as constants, never.
    """
    mod = fromText('''
    from typing import Final
    class Clazz:
        """Class."""
        def __init__(**args):
            self.LANG: Final = 'FR'
    ''', systemcls=systemcls)
    attr = mod.resolveName('Clazz.LANG')
    assert isinstance(attr, model.Attribute)
    assert attr.kind == model.DocumentableKind.INSTANCE_VARIABLE
    assert attr.value is not None
    assert ast.literal_eval(attr.value) == 'FR'
    captured = capsys.readouterr().out
    assert not captured

@systemcls_param
def test_constant_override_in_instace(systemcls: Type[model.System], capsys: CapSys) -> None:
    """
    When an instance variable overrides a CONSTANT, it's flagged as INSTANCE_VARIABLE and no warning is raised.
    """
    mod = fromText('''
    class Clazz:
        """Class."""
        LANG = 'EN'
        def __init__(self, **args):
            self.LANG = 'FR'
    ''', systemcls=systemcls, modname="mod")
    attr = mod.resolveName('Clazz.LANG')
    assert isinstance(attr, model.Attribute)
    assert attr.kind == model.DocumentableKind.INSTANCE_VARIABLE
    assert not capsys.readouterr().out

@systemcls_param
def test_constant_override_in_instace_bis(systemcls: Type[model.System], capsys: CapSys) -> None:
    """
    When an instance variable overrides a CONSTANT, it's flagged as INSTANCE_VARIABLE and no warning is raised.
    """
    mod = fromText('''
    class Clazz:
        """Class."""
        def __init__(self, **args):
            self.LANG = 'FR'
        LANG = 'EN'
    ''', systemcls=systemcls, modname="mod")
    attr = mod.resolveName('Clazz.LANG')
    assert isinstance(attr, model.Attribute)
    assert attr.kind == model.DocumentableKind.INSTANCE_VARIABLE
    assert attr.value is not None
    assert ast.literal_eval(attr.value) == 'EN'
    assert not capsys.readouterr().out

@systemcls_param
def test_constant_override_in_module(systemcls: Type[model.System], capsys: CapSys) -> None:

    mod = fromText('''
    """Mod."""
    import sys
    IS_64BITS = False
    if sys.maxsize > 2**32:
        IS_64BITS = True
    ''', systemcls=systemcls, modname="mod")
    attr = mod.resolveName('IS_64BITS')
    assert isinstance(attr, model.Attribute)
    assert attr.kind == model.DocumentableKind.VARIABLE
    assert attr.value is not None
    assert ast.literal_eval(attr.value) == True
    assert not capsys.readouterr().out

@systemcls_param
def test_constant_override_do_not_warns_when_defined_in_class_docstring(systemcls: Type[model.System], capsys: CapSys) -> None:
    """
    Constant can be documented as variables at docstring level without any warnings.
    """
    mod = fromText('''
    class Clazz:
        """
        @cvar LANG: French.
        """
        LANG = 99
    ''', systemcls=systemcls, modname="mod")
    attr = mod.resolveName('Clazz.LANG')
    assert isinstance(attr, model.Attribute)
    assert attr.kind == model.DocumentableKind.CONSTANT
    assert attr.value is not None
    assert ast.literal_eval(attr.value) == 99
    captured = capsys.readouterr().out
    assert not captured

@systemcls_param
def test_constant_override_do_not_warns_when_defined_in_module_docstring(systemcls: Type[model.System], capsys: CapSys) -> None:

    mod = fromText('''
    """
    @var LANG: French.
    """
    LANG = 99
    ''', systemcls=systemcls, modname="mod")
    attr = mod.resolveName('LANG')
    assert isinstance(attr, model.Attribute)
    assert attr.kind == model.DocumentableKind.CONSTANT
    assert attr.value is not None
    assert ast.literal_eval(attr.value) == 99
    captured = capsys.readouterr().out
    assert not captured

@systemcls_param
def test_not_a_constant_module(systemcls: Type[model.System], capsys:CapSys) -> None:
    """
    If the constant assignment has any kind of constraint or there are multiple assignments in the scope, 
    then it's not flagged as a constant.
    """
    mod = fromText('''
    while False:
        LANG = 'FR'
    if True:
        THING = 'EN'
    OTHER = 1
    OTHER += 1
    E: typing.Final = 2 # it's considered a constant because it's explicitely marked Final
    E = 4
    LIST = [2.14]
    LIST.insert(0,0)
    ''', systemcls=systemcls)
    assert mod.contents['LANG'].kind is model.DocumentableKind.VARIABLE
    assert mod.contents['THING'].kind is model.DocumentableKind.VARIABLE
    assert mod.contents['OTHER'].kind is model.DocumentableKind.VARIABLE
    assert mod.contents['E'].kind is model.DocumentableKind.CONSTANT

    # all-caps mutables variables are flagged as constant: this is a trade-off
    # in between our weeknesses in terms static analysis (that is we don't recognized list modifications) 
    # and our will to do the right thing and display constant values.
    # This issue could be overcome by showing the value of variables with only one assigment no matter
    # their kind and restrict the checks to immutable types for a attribute to be flagged as constant.
    assert mod.contents['LIST'].kind is model.DocumentableKind.CONSTANT

    # we could warn when a constant is beeing overriden, but we don't: pydoctor is not a checker.
    assert not capsys.readouterr().out 

@systemcls_param
def test__name__equals__main__is_skipped(systemcls: Type[model.System]) -> None:
    """
    Code inside of C{if __name__ == '__main__'} should be skipped.
    """
    mod = fromText('''
    foo = True

    if __name__ == '__main__':
        var = True

        def fun():
            pass

        class Class:
            pass

    def bar():
        pass
    ''', modname='test', systemcls=systemcls)
    assert tuple(mod.contents) == ('foo', 'bar')

@systemcls_param
def test__name__equals__main__is_skipped_but_orelse_processes(systemcls: Type[model.System]) -> None:
    """
    Code inside of C{if __name__ == '__main__'} should be skipped, but the else block should be processed.
    """
    mod = fromText('''
    foo = True
    if __name__ == '__main__':
        var = True
        def fun():
            pass
        class Class:
            pass
    else:
        class Very:
            ...
    def bar():
        pass
    ''', modname='test', systemcls=systemcls)
    assert tuple(mod.contents) == ('foo', 'Very', 'bar' )

@systemcls_param
def test_variable_named_like_current_module(systemcls: Type[model.System]) -> None:
    """
    Test for U{issue #474<https://github.com/twisted/pydoctor/issues/474>}.
    """
    mod = fromText('''
    example = True
    ''', systemcls=systemcls, modname="example")
    assert 'example' in mod.contents

@systemcls_param
def test_package_name_clash(systemcls: Type[model.System]) -> None:
    system = systemcls()
    builder = system.systemBuilder(system)

    builder.addModuleString('', 'mod', is_package=True)
    builder.addModuleString('', 'sub', parent_name='mod', is_package=True)

    assert isinstance(system.allobjects['mod.sub'], model.Module)

    # The following statement completely overrides module 'mod' and all it's submodules.
    builder.addModuleString('', 'mod', is_package=True)

    with pytest.raises(KeyError):
        system.allobjects['mod.sub']

    builder.addModuleString('', 'sub2', parent_name='mod', is_package=True)

    assert isinstance(system.allobjects['mod.sub2'], model.Module)

@systemcls_param
def test_reexport_wildcard(systemcls: Type[model.System]) -> None:
    """
    If a target module,
    explicitly re-export via C{__all__} a set of names
    that were initially imported from a sub-module via a wildcard,
    those names are documented as part of the target module.
    """
    system = systemcls()
    builder = system.systemBuilder(system)
    builder.addModuleString('''
    from ._impl import *
    from _impl2 import *
    __all__ = ['f', 'g', 'h', 'i', 'j']
    ''', modname='top', is_package=True)

    builder.addModuleString('''
    def f(): 
        pass
    def g():
        pass
    def h():
        pass
    ''', modname='_impl', parent_name='top')
    
    builder.addModuleString('''
    class i: pass
    class j: pass
    ''', modname='_impl2')

    builder.buildModules()

    assert system.allobjects['top._impl'].resolveName('f') == system.allobjects['top'].contents['f']
    assert system.allobjects['_impl2'].resolveName('i') == system.allobjects['top'].contents['i']
    assert all(n in system.allobjects['top'].contents for n in  ['f', 'g', 'h', 'i', 'j'])

@systemcls_param
def test_module_level_attributes_and_aliases(systemcls: Type[model.System]) -> None:
    """
    Variables and aliases defined in the main body of a Try node will have priority over the names defined in the except handlers.
    """
    system = systemcls()
    builder = system.systemBuilder(system)
    builder.addModuleString('''
    ssl = 1
    ''', modname='twisted.internet')
    builder.addModuleString('''
    try:
        from twisted.internet import ssl as _ssl
        # The names defined in the body of the if block wins over the
        # names defined in the except handler
        ssl = _ssl
        var = 1
        VAR = 1
        ALIAS = _ssl
    except ImportError:
        ssl = None
        var = 2
        VAR = 2
        ALIAS = None
    ''', modname='mod')
    builder.buildModules()
    mod = system.allobjects['mod']
    
    # Test alias
    assert mod.expandName('ssl')=="twisted.internet.ssl"
    assert mod.expandName('_ssl')=="twisted.internet.ssl"
    s = mod.resolveName('ssl')
    assert isinstance(s, model.Attribute)
    assert s.value is not None
    assert ast.literal_eval(s.value)==1
    assert s.kind == model.DocumentableKind.VARIABLE
    
    # Test variable
    assert mod.expandName('var')=="mod.var"
    v = mod.resolveName('var')
    assert isinstance(v, model.Attribute)
    assert v.value is not None
    assert ast.literal_eval(v.value)==1
    assert v.kind == model.DocumentableKind.VARIABLE

    # Test variable 2
    assert mod.expandName('VAR')=="mod.VAR"
    V = mod.resolveName('VAR')
    assert isinstance(V, model.Attribute)
    assert V.value is not None
    assert ast.literal_eval(V.value)==1
    assert V.kind == model.DocumentableKind.VARIABLE

    # Test variable 3
    assert mod.expandName('ALIAS')=="twisted.internet.ssl"
    s = mod.resolveName('ALIAS')
    assert isinstance(s, model.Attribute)
    assert s.value is not None
    assert ast.literal_eval(s.value)==1
    assert s.kind == model.DocumentableKind.VARIABLE

@systemcls_param
def test_module_level_attributes_and_aliases_orelse(systemcls: Type[model.System]) -> None:
    """
    We visit the try orelse body and these names have priority over the names in the except handlers.
    """
    system = systemcls()
    builder = system.systemBuilder(system)
    builder.addModuleString('''
    ssl = 1
    ''', modname='twisted.internet')
    builder.addModuleString('''
    try:
        from twisted.internet import ssl as _ssl
    except ImportError:
        ssl = None
        var = 2
        VAR = 2
        ALIAS = None
        newname = 2
    else:
        # The names defined in the orelse or finally block wins over the
        # names defined in the except handler
        ssl = _ssl
        var = 1
    finally:
        VAR = 1
        ALIAS = _ssl
    
    if sys.version_info > (3,7):
        def func():
            'func doc'
        class klass:
            'klass doc'
        var2 = 1
        'var2 doc'
    else:
        # these definition will be ignored since they are
        # alreade definied in the body of the If block.
        func = None
        'not this one'
        def klass():
            'not this one'
        class var2:
            'not this one'
    ''', modname='mod')
    builder.buildModules()
    mod = system.allobjects['mod']

    # Tes newname survives the override guard
    assert 'newname' in mod.contents
    
    # Test alias
    assert mod.expandName('ssl')=="twisted.internet.ssl"
    assert mod.expandName('_ssl')=="twisted.internet.ssl"
    s = mod.resolveName('ssl')
    assert isinstance(s, model.Attribute)
    assert s.value is not None
    assert ast.literal_eval(s.value)==1
    assert s.kind == model.DocumentableKind.VARIABLE
    
    # Test variable
    assert mod.expandName('var')=="mod.var"
    v = mod.resolveName('var')
    assert isinstance(v, model.Attribute)
    assert v.value is not None
    assert ast.literal_eval(v.value)==1
    assert v.kind == model.DocumentableKind.VARIABLE

    # Test variable 2
    assert mod.expandName('VAR')=="mod.VAR"
    V = mod.resolveName('VAR')
    assert isinstance(V, model.Attribute)
    assert V.value is not None
    assert ast.literal_eval(V.value)==1
    assert V.kind == model.DocumentableKind.VARIABLE

    # Test variable 3
    assert mod.expandName('ALIAS')=="twisted.internet.ssl"
    s = mod.resolveName('ALIAS')
    assert isinstance(s, model.Attribute)
    assert s.value is not None
    assert ast.literal_eval(s.value)==1
    assert s.kind == model.DocumentableKind.VARIABLE

    # Test if override guard
    func, klass, var2 = mod.resolveName('func'), mod.resolveName('klass'), mod.resolveName('var2')
    assert isinstance(func, model.Function) 
    assert func.docstring == 'func doc'
    assert isinstance(klass, model.Class)
    assert klass.docstring == 'klass doc'
    assert isinstance(var2, model.Attribute)
    assert var2.docstring == 'var2 doc'

@systemcls_param
def test_method_level_orelse_handlers_use_case1(systemcls: Type[model.System]) -> None:
    system = systemcls()
    builder = system.systemBuilder(system)
    builder.addModuleString('''
    class K:
        def test(self, ):...
        def __init__(self, text):
            try:
                self.test()
            except:
                # Even if this attribute is only defined in the except block in a function/method
                # it will be included in the documentation. 
                self.error = True
            finally:
                self.name = text
                if sys.version_info > (3,0):
                    pass
                elif sys.version_info > (2,6):
                    # Idem for these instance attributes
                    self.legacy = True
                    self.still_supported = True
                else:
                    # This attribute is ignored, the same rules that applies
                    # at the module level applies here too.
                    # since it's already defined in the upper block If.body
                    # this assigment is ignored.
                    self.still_supported = False
    ''', modname='mod')
    builder.buildModules()
    mod = system.allobjects['mod']
    assert isinstance(mod, model.Module)
    K = mod.contents['K']
    assert isinstance(K, model.Class)
    assert K.resolveName('legacy') == K.contents['legacy']
    assert K.resolveName('error') == K.contents['error']
    assert K.resolveName('name') == K.contents['name']
    s = K.contents['still_supported']
    assert K.resolveName('still_supported') == s
    assert isinstance(s, model.Attribute)
    assert ast.literal_eval(s.value or '') == True

@systemcls_param
def test_method_level_orelse_handlers_use_case2(systemcls: Type[model.System]) -> None:
    system = systemcls()
    builder = system.systemBuilder(system)
    builder.addModuleString('''
    class K:
        def __init__(self, d:dict, g:Iterator):
            try:
                next(g)
            except StopIteration:
                # this should be documented
                self.data = d
            else:
                raise RuntimeError("the generator wasn't exhausted!")
            finally:
                if sys.version_info < (3,7):
                    raise RuntimeError("please upadate your python version to 3.7 al least!")
                else:
                    # Idem for this instance attribute
                    self.ok = True
    ''', modname='mod')
    builder.buildModules()
    mod = system.allobjects['mod']
    assert isinstance(mod, model.Module)
    K = mod.contents['K']
    assert isinstance(K, model.Class)
    assert K.resolveName('data') == K.contents['data']
    assert K.resolveName('ok') == K.contents['ok']


@systemcls_param
def test_class_level_attributes_and_aliases_orelse(systemcls: Type[model.System]) -> None:
    system = systemcls()
    builder = system.systemBuilder(system)
    builder.addModuleString('crazy_var=2', modname='crazy')
    builder.addModuleString('''
    if sys.version_info > (3,0):
        thing = object
        class klass(thing):
            'klass doc'
            var2 = 3
        
        # regular import
        from crazy import crazy_var as cv
    else:
        # these imports will be ignored because the names
        # have been defined in the body of the If block.
        from six import t as thing 
        import klass
        from crazy27 import crazy_var as cv

        # Wildcard imports are still processed 
        # in name override guard context
        from crazy import * 

        # this import is not ignored
        from six import seven

        # this class is not ignored and will be part of the public docs.
        class klassfallback(thing): 
            'klassfallback doc'
            var2 = 1
            # this overrides var2
            var2 = 2 
        
        # this is ignored because the name 'klass' 
        # has been defined in the body of the If block.
        klass = klassfallback                 
        'ignored'

        var3 = 1
        # this overrides var3
        var3 = 2 
    ''', modname='mod')
    builder.buildModules()
    mod = system.allobjects['mod']
    assert isinstance(mod, model.Module)

    klass, klassfallback, var2, var3 = \
        mod.resolveName('klass'), \
        mod.resolveName('klassfallback'), \
        mod.resolveName('klassfallback.var2'), \
        mod.resolveName('var3')

    assert isinstance(klass, model.Class)
    assert isinstance(klassfallback, model.Class)
    assert isinstance(var2, model.Attribute)
    assert isinstance(var3, model.Attribute)

    assert klassfallback.docstring == 'klassfallback doc'
    assert klass.docstring == 'klass doc'
    assert ast.literal_eval(var2.value or '') == 2
    assert ast.literal_eval(var3.value or '') == 2
    
    assert mod.expandName('cv') == 'crazy.crazy_var'
    assert mod.expandName('thing') == 'object'
    assert mod.expandName('seven') == 'six.seven'
    assert 'klass' not in mod._localNameToFullName_map
    assert 'crazy_var' in mod._localNameToFullName_map # from the wildcard

@systemcls_param
def test_exception_kind(systemcls: Type[model.System], capsys: CapSys) -> None:
    """
    Exceptions are marked with the special kind "EXCEPTION".
    """
    mod = fromText('''
    class Clazz:
        """Class."""
    class MyWarning(DeprecationWarning):
        """Warnings are technically exceptions"""
    class Error(SyntaxError):
        """An exeption"""
    class SubError(Error):
        """A exeption subclass"""  
    ''', systemcls=systemcls, modname="mod")
    
    warn = mod.contents['MyWarning']
    ex1 = mod.contents['Error']
    ex2 = mod.contents['SubError']
    cls = mod.contents['Clazz']

    assert warn.kind is model.DocumentableKind.EXCEPTION
    assert ex1.kind is model.DocumentableKind.EXCEPTION
    assert ex2.kind is model.DocumentableKind.EXCEPTION
    assert cls.kind is model.DocumentableKind.CLASS

    assert not capsys.readouterr().out

@systemcls_param
def test_exception_kind_corner_cases(systemcls: Type[model.System], capsys: CapSys) -> None:

    src1 = '''\
    class Exception:...
    class LooksLikeException(Exception):... # Not an exception
    '''

    src2 = '''\
    class Exception(BaseException):...
    class LooksLikeException(Exception):... # An exception
    '''

    mod1 = fromText(src1, modname='src1', systemcls=systemcls)
    assert mod1.contents['LooksLikeException'].kind == model.DocumentableKind.CLASS

    mod2 = fromText(src2, modname='src2', systemcls=systemcls)
    assert mod2.contents['LooksLikeException'].kind == model.DocumentableKind.EXCEPTION

    assert not capsys.readouterr().out
    
@systemcls_param
def test_syntax_error(systemcls: Type[model.System], capsys: CapSys) -> None:
    systemcls = partialclass(systemcls, Options.from_args(['-q']))
    fromText('''\
    def f()
        return True
    ''', systemcls=systemcls)
    assert capsys.readouterr().out == '<test>:???: cannot parse string\n'

@systemcls_param
def test_syntax_error_pack(systemcls: Type[model.System], capsys: CapSys) -> None:
    systemcls = partialclass(systemcls, Options.from_args(['-q']))
    processPackage('syntax_error', systemcls)
    out = capsys.readouterr().out.strip('\n')
    assert "__init__.py:???: cannot parse file, " in out, out

@systemcls_param
def test_type_alias(systemcls: Type[model.System]) -> None:
    """
    Type aliases and type variables are recognized as such.
    """

    mod = fromText(
        '''
        from typing import Callable, Tuple, TypeAlias, TypeVar
        
        T = TypeVar('T')
        Parser = Callable[[str], Tuple[int, bytes, bytes]]
        mylst = yourlst = list[str]
        alist: TypeAlias = 'list[str]'
        
        notanalias = 'Callable[[str], Tuple[int, bytes, bytes]]'

        class F:
            from ext import what
            L = _j = what.some = list[str]
            def __init__(self):
                self.Pouet: TypeAlias = 'Callable[[str], Tuple[int, bytes, bytes]]'
                self.Q = q = list[str]
        
        ''', systemcls=systemcls)

    assert mod.contents['T'].kind == model.DocumentableKind.TYPE_VARIABLE
    assert mod.contents['Parser'].kind == model.DocumentableKind.TYPE_ALIAS
    assert mod.contents['mylst'].kind == model.DocumentableKind.TYPE_ALIAS
    assert mod.contents['yourlst'].kind == model.DocumentableKind.TYPE_ALIAS
    assert mod.contents['alist'].kind == model.DocumentableKind.TYPE_ALIAS
    assert mod.contents['notanalias'].kind == model.DocumentableKind.VARIABLE
    assert mod.contents['F'].contents['L'].kind == model.DocumentableKind.TYPE_ALIAS
    assert mod.contents['F'].contents['_j'].kind == model.DocumentableKind.TYPE_ALIAS

    # Type variables in instance variables are not recognized
    assert mod.contents['F'].contents['Pouet'].kind == model.DocumentableKind.INSTANCE_VARIABLE
    assert mod.contents['F'].contents['Q'].kind == model.DocumentableKind.INSTANCE_VARIABLE

@systemcls_param
def test_typevartuple(systemcls: Type[model.System]) -> None:
    """
    Variadic type variables are recognized.
    """

    mod = fromText('''
    from typing import TypeVarTuple
    Shape = TypeVarTuple('Shape')
    ''', systemcls=systemcls)

    assert mod.contents['Shape'].kind == model.DocumentableKind.TYPE_VARIABLE

@systemcls_param
def test_prepend_package(systemcls: Type[model.System]) -> None:
    """
   Option --prepend-package option relies simply on the L{ISystemBuilder} interface, 
   so we can test it by using C{addModuleString}, but it's not exactly what happens when we actually 
   run pydoctor. See the other test L{test_prepend_package_real_path}. 
    """
    system = systemcls()
    builder = model.prepend_package(system.systemBuilder, package='lib.pack')(system)

    builder.addModuleString('"mod doc"\nclass C:\n    "C doc"', modname='core')
    builder.buildModules()
    assert isinstance(system.allobjects['lib'], model.Package)
    assert isinstance(system.allobjects['lib.pack'], model.Package)
    assert isinstance(system.allobjects['lib.pack.core.C'], model.Class)
    assert 'core' not in system.allobjects


@systemcls_param
def test_prepend_package_real_path(systemcls: Type[model.System]) -> None:
    """ 
    In this test, we closer mimics what happens in the driver when --prepend-package option is passed. 
    """
    _builderT_init = systemcls.systemBuilder
    try:
        systemcls.systemBuilder = model.prepend_package(systemcls.systemBuilder, package='lib.pack')

        system = processPackage('basic', systemcls=systemcls)

        assert isinstance(system.allobjects['lib'], model.Package)
        assert isinstance(system.allobjects['lib.pack'], model.Package)
        assert isinstance(system.allobjects['lib.pack.basic.mod.C'], model.Class)
        assert 'basic' not in system.allobjects
    
    finally:
        systemcls.systemBuilder = _builderT_init

def getConstructorsText(cls: model.Documentable) -> str:
    assert isinstance(cls, model.Class)
    return '\n'.join(
        epydoc2stan.format_constructor_short_text(c, cls) for c in cls.public_constructors)

@systemcls_param
def test_crash_type_inference_unhashable_type(systemcls: Type[model.System], capsys:CapSys) -> None:
    """
    This test is about not crashing.

    A TypeError is raised by ast.literal_eval() in some cases, when we're trying to do a set of lists or a dict with list keys.
    We do not bother reporting it because pydoctor is not a checker.
    """

    src = '''
    # Unhashable type, will raise an error in ast.literal_eval()
    x = {[1, 2]}
    class C:
        v = {[1,2]:1}
        def __init__(self):
            self.y = [{'str':2}, {[1,2]:1}]
    Y = [{'str':2}, {{[1, 2]}:1}]
    '''

    mod = fromText(src, systemcls=systemcls, modname='m')
    for obj in ['m.x', 'm.C.v', 'm.C.y', 'm.Y']:
        o = mod.system.allobjects[obj]
        assert isinstance(o, model.Attribute)
        assert o.annotation is None
    assert not capsys.readouterr().out


@systemcls_param
def test_constructor_signature_init(systemcls: Type[model.System]) -> None:
    
    src = '''\
    class Person(object):
        # pydoctor can infer the constructor to be: "Person(name, age)"
        def __init__(self, name, age):
            self.name = name
            self.age = age

    class Citizen(Person):
        # pydoctor can infer the constructor to be: "Citizen(nationality, *args, **kwargs)"
        def __init__(self, nationality, *args, **kwargs):
            self.nationality = nationality
            super(Citizen, self).__init__(*args, **kwargs)
        '''
    mod = fromText(src, systemcls=systemcls)

    # Like "Available constructor: ``Person(name, age)``" that links to Person.__init__ documentation.
    assert getConstructorsText(mod.contents['Person']) == "Person(name, age)"
    
    # Like "Available constructor: ``Citizen(nationality, *args, **kwargs)``" that links to Citizen.__init__ documentation.
    assert getConstructorsText(mod.contents['Citizen']) == "Citizen(nationality, *args, **kwargs)"

@systemcls_param
def test_constructor_signature_new(systemcls: Type[model.System]) -> None:
    src = '''\
    class Animal(object):
        # pydoctor can infer the constructor to be: "Animal(name)"
        def __new__(cls, name):
            obj = super().__new__(cls)
            # assignation not recognized by pydoctor, attribute 'name' will not be documented
            obj.name = name 
            return obj
    '''

    mod = fromText(src, systemcls=systemcls)

    assert getConstructorsText(mod.contents['Animal']) == "Animal(name)"

@systemcls_param
def test_constructor_signature_init_and_new(systemcls: Type[model.System]) -> None:
    """
    Pydoctor can't infer the constructor signature when both __new__ and __init__ are defined. 
    __new__ takes the precedence over __init__ because it's called first. Trying to infer what are the complete 
    constructor signature when __new__ is defined might be very hard because the method can return an instance of 
    another class, calling another __init__ method. We're not there yet in term of static analysis.
    """

    src = '''\
    class Animal(object):
        # both __init__ and __new__ are defined, pydoctor only looks at the __new__ method
        # pydoctor infers the constructor to be: "Animal(*args, **kw)"
        def __new__(cls, *args, **kw):
            print('__new__() called.')
            print('args: ', args, ', kw: ', kw)
            return super().__new__(cls)

        def __init__(self, name):
            print('__init__() called.')
            self.name = name
            
    class Cat(Animal):
        # Idem, but __new__ is inherited.
        # pydoctor infers the constructor to be: "Cat(*args, **kw)"
        # This is why it's important to still document __init__ as a regular method.
        def __init__(self, name, owner):
            super().__init__(name)
            self.owner = owner
    '''

    mod = fromText(src, systemcls=systemcls)

    assert getConstructorsText(mod.contents['Animal']) == "Animal(*args, **kw)"
    assert getConstructorsText(mod.contents['Cat']) == "Cat(*args, **kw)"

@systemcls_param
def test_constructor_signature_classmethod(systemcls: Type[model.System]) -> None:

    src = '''\
    
    def get_default_options() -> 'Options':
        """
        This is another constructor for class 'Options'. 
        But it's not recognized by pydoctor because it's not defined in the locals of Options.
        """
        return Options()

    class Options:
        a,b,c = None, None, None

        @classmethod
        def create_no_hints(cls):
            """
            Pydoctor can't deduce that this method is a constructor as well,
            because there is no type annotation.
            """
            return cls()
        
        # thanks to type hints, 
        # pydoctor can infer the constructor to be: "Options.create()"
        @staticmethod
        def create(important_arg) -> 'Options':
            # the fictional constructor is not detected by pydoctor, because it doesn't exists actually.
            return Options(1,2,3)
        
        # thanks to type hints, 
        # pydoctor can infer the constructor to be: "Options.create_from_num(num)"
        @classmethod
        def create_from_num(cls, num) -> 'Options':
            c = cls.create()
            c.a = num
            return c
        '''

    mod = fromText(src, systemcls=systemcls)

    assert getConstructorsText(mod.contents['Options']) == "Options.create(important_arg)\nOptions.create_from_num(num)"

@systemcls_param
def test_constructor_inner_class(systemcls: Type[model.System]) -> None:
    src = '''\
    from typing import Self
    class Animal(object):
        class Bar(object):
            # pydoctor can infer the constructor to be: "Animal.Bar(name)"
            def __new__(cls, name):
                ...
            class Foo(object):
                # pydoctor can infer the constructor to be: "Animal.Bar.Foo.create(name)"
                @classmethod
                def create(cls, name) -> 'Self':
                    c = cls.create()
                    c.a = num
                    return c
    '''
    mod = fromText(src, systemcls=systemcls)
    assert getConstructorsText(mod.contents['Animal'].contents['Bar']) == "Animal.Bar(name)"
    assert getConstructorsText(mod.contents['Animal'].contents['Bar'].contents['Foo']) == "Animal.Bar.Foo.create(name)"

@systemcls_param
def test_constructor_many_parameters(systemcls: Type[model.System]) -> None:
    src = '''\
    class Animal(object):
        def __new__(cls, name, lastname, age, spec, extinct, group, friends):
            ...
    '''
    mod = fromText(src, systemcls=systemcls)

    assert getConstructorsText(mod.contents['Animal']) == "Animal(name, lastname, age, spec, ...)"

@systemcls_param
def test_constructor_five_paramters(systemcls: Type[model.System]) -> None:
    src = '''\
    class Animal(object):
        def __new__(cls, name, lastname, age, spec, extinct):
            ...
    '''
    mod = fromText(src, systemcls=systemcls)

    assert getConstructorsText(mod.contents['Animal']) == "Animal(name, lastname, age, spec, extinct)"

@systemcls_param
def test_default_constructors(systemcls: Type[model.System]) -> None:
    src = '''\
    class Animal(object):
        def __init__(self):
            ...
        def __new__(cls):
            ...
        @classmethod
        def new(cls) -> 'Animal':
            ...
        '''

    mod = fromText(src, systemcls=systemcls)
    assert getConstructorsText(mod.contents['Animal']) == "Animal.new()"

    src = '''\
    class Animal(object):
        def __init__(self):
            ...
        '''

    mod = fromText(src, systemcls=systemcls)
    assert getConstructorsText(mod.contents['Animal']) == ""

    src = '''\
    class Animal(object):
        def __init__(self):
            "thing"
        '''

    mod = fromText(src, systemcls=systemcls)
    assert getConstructorsText(mod.contents['Animal']) == "Animal()"

@systemcls_param
def test_class_var_override(systemcls: Type[model.System]) -> None:

    src = '''\
    from number import Number
    class Thing(object):
        def __init__(self):
            self.var: Number = 1
    class Stuff(Thing):
        var:float
        '''

    mod = fromText(src, systemcls=systemcls, modname='mod')
    var = mod.system.allobjects['mod.Stuff.var']
    assert var.kind == model.DocumentableKind.INSTANCE_VARIABLE

@systemcls_param
def test_class_var_override_traverse_subclasses(systemcls: Type[model.System]) -> None:

    src = '''\
    from number import Number
    class Thing(object):
        def __init__(self):
            self.var: Number = 1
    class _Stuff(Thing):
        ...
    class Stuff(_Stuff):
        var:float
        '''

    mod = fromText(src, systemcls=systemcls, modname='mod')
    var = mod.system.allobjects['mod.Stuff.var']
    assert var.kind == model.DocumentableKind.INSTANCE_VARIABLE

    src = '''\
    from number import Number
    class Thing(object):
        def __init__(self):
            self.var: Optional[Number] = 0
    class _Stuff(Thing):
        var = None
    class Stuff(_Stuff):
        var: float
        '''

    mod = fromText(src, systemcls=systemcls, modname='mod')
    var = mod.system.allobjects['mod._Stuff.var']
    assert var.kind == model.DocumentableKind.INSTANCE_VARIABLE
    
    mod = fromText(src, systemcls=systemcls, modname='mod')
    var = mod.system.allobjects['mod.Stuff.var']
    assert var.kind == model.DocumentableKind.INSTANCE_VARIABLE

def test_class_var_override_attrs() -> None:

    systemcls = AttrsSystem

    src = '''\
    import attr
    @attr.s
    class Thing(object):
        var = attr.ib()
    class Stuff(Thing):
        var: float
        '''

    mod = fromText(src, systemcls=systemcls, modname='mod')
    var = mod.system.allobjects['mod.Stuff.var']
    assert var.kind == model.DocumentableKind.INSTANCE_VARIABLE

@systemcls_param
def test_explicit_annotation_wins_over_inferred_type(systemcls: Type[model.System]) -> None:
    """
    Explicit annotations are the preffered way of presenting the type of an attribute.
    """
    src = '''\
    class Stuff(object):
        thing: List[Tuple[Thing, ...]]
        def __init__(self):
            self.thing = []
        '''
    mod = fromText(src, systemcls=systemcls, modname='mod')
    thing = mod.system.allobjects['mod.Stuff.thing']
    assert flatten_text(epydoc2stan.type2stan(thing)) == "List[Tuple[Thing, ...]]" #type:ignore

    src = '''\
    class Stuff(object):
        thing = []
        def __init__(self):
            self.thing: List[Tuple[Thing, ...]] = []
        '''
    mod = fromText(src, systemcls=systemcls, modname='mod')
    thing = mod.system.allobjects['mod.Stuff.thing']
    assert flatten_text(epydoc2stan.type2stan(thing)) == "List[Tuple[Thing, ...]]" #type:ignore

@systemcls_param
def test_explicit_inherited_annotation_looses_over_inferred_type(systemcls: Type[model.System]) -> None:
    """
    Annotation are of inherited.
    """
    src = '''\
    class _Stuff(object):
        thing: List[Tuple[Thing, ...]]
    class Stuff(_Stuff):
        def __init__(self):
            self.thing = []
        '''
    mod = fromText(src, systemcls=systemcls, modname='mod')
    thing = mod.system.allobjects['mod.Stuff.thing']
    assert flatten_text(epydoc2stan.type2stan(thing)) == "list" #type:ignore

@systemcls_param
def test_inferred_type_override(systemcls: Type[model.System]) -> None:
    """
    The last visited value will be used to infer the type annotation
    of an unnanotated attribute.
    """
    src = '''\
    class Stuff(object):
        thing = 1
        def __init__(self):
            self.thing = (1,2)
        '''
    mod = fromText(src, systemcls=systemcls, modname='mod')
    thing = mod.system.allobjects['mod.Stuff.thing']
    assert flatten_text(epydoc2stan.type2stan(thing)) == "tuple[int, ...]" #type:ignore

@systemcls_param
def test_inferred_type_is_not_propagated_to_subclasses(systemcls: Type[model.System]) -> None:
    """
    Inferred type annotation should not be propagated to subclasses.
    """
    src = '''\
    class _Stuff(object):
        def __init__(self):
            self.thing = []
    class Stuff(_Stuff):
        def __init__(self, thing):
            self.thing = thing
        '''
    mod = fromText(src, systemcls=systemcls, modname='mod')
    thing = mod.system.allobjects['mod.Stuff.thing']
    assert epydoc2stan.type2stan(thing) is None


@systemcls_param
def test_inherited_type_is_not_propagated_to_subclasses(systemcls: Type[model.System]) -> None:
    """
    We can't repliably propage the annotations from one class to it's subclass because of 
    issue https://github.com/twisted/pydoctor/issues/295.
    """
    src1 = '''\
    class _s:...
    class _Stuff(object):
        def __init__(self):
            self.thing:_s = []
    '''
    src2 = '''\
    from base import _Stuff, _s
    class Stuff(_Stuff):
        def __init__(self, thing):
            self.thing = thing
    __all__=['Stuff', '_s']
        '''
    system = systemcls()
    builder = system.systemBuilder(system)
    builder.addModuleString(src1, 'base')
    builder.addModuleString(src2, 'mod')
    builder.buildModules()
    thing = system.allobjects['mod.Stuff.thing']
    assert epydoc2stan.type2stan(thing) is None

@systemcls_param
def test_augmented_assignment(systemcls: Type[model.System]) -> None:
    mod = fromText('''
    var = 1
    var += 3
    ''', systemcls=systemcls)
    attr = mod.contents['var']
    assert isinstance(attr, model.Attribute)
    assert attr.value
    assert astutils.unparse(attr.value).strip() == '1 + 3'

@systemcls_param
def test_augmented_assignment_in_class(systemcls: Type[model.System]) -> None:
    mod = fromText('''
    class c:
        var = 1
        var += 3
    ''', systemcls=systemcls)
    attr = mod.contents['c'].contents['var']
    assert isinstance(attr, model.Attribute)
    assert attr.value
    assert astutils.unparse(attr.value).strip() == '1 + 3'


@systemcls_param
def test_augmented_assignment_conditionnal_else_ignored(systemcls: Type[model.System]) -> None:
    """
    The If.body branch is the only one in use.
    """
    mod = fromText('''
    var = 1
    if something():
        var += 3
    else:
        var += 4
    ''', systemcls=systemcls)
    attr = mod.contents['var']
    assert isinstance(attr, model.Attribute)
    assert attr.value
    assert astutils.unparse(attr.value).strip() == '1 + 3'

@systemcls_param
def test_augmented_assignment_conditionnal_multiple_assignments(systemcls: Type[model.System]) -> None:
    """
    The If.body branch is the only one in use, but several Ifs which have  
    theoritical exclusive conditions might be wrongly interpreted.
    """
    mod = fromText('''
    var = 1
    if something():
        var += 3
    if not_something():
        var += 4
    ''', systemcls=systemcls)
    attr = mod.contents['var']
    assert isinstance(attr, model.Attribute)
    assert attr.value
    assert astutils.unparse(attr.value).strip() == '1 + 3 + 4'

@systemcls_param
def test_augmented_assignment_instance_var(systemcls: Type[model.System]) -> None:
    """
    Augmented assignments in instance var are not analyzed.
    """
    mod = fromText('''
    class c:
        def __init__(self, var):
            self.var = 1
            self.var += var
        ''')
    attr = mod.contents['c'].contents['var']
    assert isinstance(attr, model.Attribute)
    assert attr.value
    assert astutils.unparse(attr.value).strip() == '1'

@systemcls_param
def test_augmented_assignment_not_suitable_for_inline_docstring(systemcls: Type[model.System]) -> None:
    """
    Augmented assignments cannot have docstring attached.
    """
    mod = fromText('''
    var = 1
    var += 1
    """
    this is not a docstring
    """
    class c:
        var = 1
        var += 1
        """
        this is not a docstring
        """
        ''')
    attr = mod.contents['var']
    assert not attr.docstring
    attr = mod.contents['c'].contents['var']
    assert not attr.docstring

@systemcls_param
def test_augmented_assignment_alone_is_not_documented(systemcls: Type[model.System]) -> None:
    mod = fromText('''
    var += 1
    class c:
        var += 1
        ''')

    assert 'var' not in mod.contents
    assert 'var' not in mod.contents['c'].contents

@systemcls_param
def test_typealias_unstring(systemcls: Type[model.System]) -> None:
    """
    The type aliases are unstringed by the astbuilder
    """
    
    mod = fromText('''
    from typing import Callable
    ParserFunction = Callable[[str, List['ParseError']], 'ParsedDocstring']
    ''', modname='pydoctor.epydoc.markup', systemcls=systemcls)

    typealias = mod.contents['ParserFunction']
    assert isinstance(typealias, model.Attribute)
    assert typealias.value
    with pytest.raises(StopIteration):
        # there is not Constant nodes in the type alias anymore
        next(n for n in ast.walk(typealias.value) if isinstance(n, ast.Constant))

@systemcls_param
def test_mutilple_docstrings_warnings(systemcls: Type[model.System], capsys: CapSys) -> None:
    """
    When pydoctor encounters multiple places where the docstring is defined, it reports a warning.
    """
    src = '''
    class C:
        a: int;"docs"
        def _(self):
            self.a = 0; "re-docs"
    
    class B:
        """
        @ivar a: docs
        """
        a: int
        "re-docs"
    
    class A:
        """docs"""
        A.__doc__ = 're-docs'
    '''
    fromText(src, systemcls=systemcls)
    assert capsys.readouterr().out == ('<test>:5: Existing docstring at line 3 is overriden\n'
                                       '<test>:12: Existing docstring at line 9 is overriden\n'
                                       '<test>:16: Existing docstring at line 15 is overriden\n')

@systemcls_param
def test_mutilple_docstring_with_doc_comments_warnings(systemcls: Type[model.System], capsys: CapSys) -> None:
    src = '''
    class C:
        a: int;"docs" #: re-docs
    
    class B:
        """
        @ivar a: docs
        """
        #: re-docs
        a: int 

    class B2:
        """
        @ivar a: docs
        """
        #: re-docs
        a: int 
        "re-re-docs"
    '''
    fromText(src, systemcls=systemcls)
    # TODO: handle doc comments.x
    assert capsys.readouterr().out == '<test>:18: Existing docstring at line 14 is overriden\n'

@systemcls_param
def test_import_all_inside_else_branch_is_processed(systemcls: Type[model.System], capsys: CapSys) -> None:
    src1 = '''
    Callable = ...
    '''

    src2 = '''
    Callable = ...
    TypeAlias = ...
    '''

    src0 = '''
    import sys
    if sys.version_info > (3, 10):
        from typing import *
    else:
        from typing_extensions import *
    '''

    system = systemcls()
    builder = systemcls.systemBuilder(system)
    builder.addModuleString(src0, 'main')
    builder.addModuleString(src1, 'typing')
    builder.addModuleString(src2, 'typing_extensions')
    builder.buildModules()
    # assert not capsys.readouterr().out
    main = system.allobjects['main']
    assert list(main.localNames()) == ['sys', 'Callable', 'TypeAlias'] # type: ignore
    assert main.expandName('Callable') == 'typing.Callable'
    assert main.expandName('TypeAlias') == 'typing_extensions.TypeAlias'

@systemcls_param
def test_inline_docstring_multiple_assigments(systemcls: Type[model.System], capsys: CapSys) -> None:
    # TODO: this currently does not support nested tuple assignments.
    src = '''
    class C:
        def __init__(self):
            self.x, x = 1, 1; 'x docs'
            self.y = x = 1; 'y docs'
    x,y = 1,1; 'x and y docs'
    v = w = 1; 'v and w docs'
    '''
    mod =  fromText(src, systemcls=systemcls)
    assert not capsys.readouterr().out
    assert mod.contents['x'].docstring == 'x and y docs'
    assert mod.contents['y'].docstring == 'x and y docs'
    assert mod.contents['v'].docstring == 'v and w docs'
    assert mod.contents['w'].docstring == 'v and w docs'
    assert mod.contents['C'].contents['x'].docstring == 'x docs'
    assert mod.contents['C'].contents['y'].docstring == 'y docs'


@systemcls_param
def test_does_not_misinterpret_string_as_documentation(systemcls: Type[model.System], capsys: CapSys) -> None:
    # exmaple from numpy/distutils/ccompiler_opt.py
    src = '''
    __docformat__ = 'numpy'
    class C:
        """
        Attributes
        ----------
        cc_noopt : bool
            docs
        """
        def __init__(self):
            self.cc_noopt = x

            if True:
                """
                this is not documentation
                """
    '''

    mod =  fromText(src, systemcls=systemcls)
    assert _get_docformat(mod) == 'numpy'
    assert not capsys.readouterr().out
    assert mod.contents['C'].contents['cc_noopt'].docstring is None 
    # The docstring is None... this is the sad side effect of processing ivar fields :/

    assert to_html(mod.contents['C'].contents['cc_noopt'].parsed_docstring) == 'docs' #type:ignore

@systemcls_param
def test_unsupported_usage_of_self(systemcls: Type[model.System], capsys: CapSys) -> None:
    src = '''
    class C:
        ...
    def C_init(self):
        self.x = True; 'not documentation'
        self.y += False # erroneous usage of augassign; 'not documentation'
    C.__init__ = C_init

    self = object()
    self.x = False
    """
    not documentation
    """
    '''
    mod =  fromText(src, systemcls=systemcls)
    assert not capsys.readouterr().out
    assert list(mod.contents['C'].contents) == []
    assert not mod.contents['self'].docstring

@systemcls_param
def test_inline_docstring_at_wrong_place(systemcls: Type[model.System], capsys: CapSys) -> None:
    src = '''
    a = objetc()
    a.b = True
    """
    not documentation
    """
    b = object()
    b.x: bool = False
    """
    still not documentation
    """
    c = {}
    c[1] = True
    """
    Again not documenatation
    """
    d = {}
    d[1].__init__ = True
    """
    Again not documenatation
    """
    e = {}
    e[1].__init__ += True
    """
    Again not documenatation
    """
    '''
    mod =  fromText(src, systemcls=systemcls)
    assert not capsys.readouterr().out
    assert list(mod.contents) == ['a', 'b', 'c', 'd', 'e']
    assert not mod.contents['a'].docstring
    assert not mod.contents['b'].docstring
    assert not mod.contents['c'].docstring
    assert not mod.contents['d'].docstring
    assert not mod.contents['e'].docstring

@systemcls_param
def test_Final_constant_under_control_flow_block_is_still_constant(systemcls: Type[model.System], capsys: CapSys) -> None:
    """
    Test for issue https://github.com/twisted/pydoctor/issues/818
    """
    src = '''
    import sys, random, typing as t
    if sys.version_info > (3,10):
        v:t.Final = 1
    else:
        v:t.Final = 2
    
    if random.choice([True, False]):
        w:t.Final = 1
    else:
        w:t.Final = 2
    
    x: t.Final
    x = 34
    '''

    mod =  fromText(src, systemcls=systemcls)
    assert not capsys.readouterr().out

    assert mod.contents['v'].kind == model.DocumentableKind.CONSTANT
    assert mod.contents['w'].kind == model.DocumentableKind.CONSTANT
    assert mod.contents['x'].kind == model.DocumentableKind.CONSTANT
    
