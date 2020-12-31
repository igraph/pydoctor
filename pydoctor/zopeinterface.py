"""Support for Zope interfaces."""

from typing import Iterable, Iterator, List, Optional, Union
import ast
import re

import astor

from pydoctor import astbuilder, model


class ZopeInterfaceModule(model.Module):

    def setup(self) -> None:
        super().setup()
        self.implements_directly: List[str] = []

    @property
    def allImplementedInterfaces(self) -> Iterable[str]:
        """Return all the interfaces provided by this module
        """
        return self.implements_directly


class ZopeInterfaceClass(model.Class):
    isinterface = False
    isschemafield = False
    isinterfaceclass = False
    implementsOnly = False

    implementedby_directly: List[Union['ZopeInterfaceClass', ZopeInterfaceModule]]
    """Only defined when isinterface == True."""

    baseobjects: List[Optional['ZopeInterfaceClass']]  # type: ignore[assignment]
    subclasses: List['ZopeInterfaceClass']  # type: ignore[assignment]

    def setup(self) -> None:
        super().setup()
        self.implements_directly: List[str] = []

    @property
    def allImplementedInterfaces(self) -> Iterable[str]:
        """Return all the interfaces implemented by this class.

        This returns them in something like the classic class MRO.
        """
        if self.implementsOnly:
            return self.implements_directly
        r = list(self.implements_directly)
        for b in self.baseobjects:
            if b is None:
                continue
            for interface in b.allImplementedInterfaces:
                if interface not in r:
                    r.append(interface)
        return r

def _inheritedDocsources(obj: model.Documentable) -> Iterator[model.Documentable]:
    if not isinstance(obj.parent, (ZopeInterfaceClass, ZopeInterfaceModule)):
        return
    name = obj.name
    for interface in obj.parent.allImplementedInterfaces:
        io = obj.system.objForFullName(interface)
        if io is not None:
            assert isinstance(io, ZopeInterfaceClass)
            for io2 in io.allbases(include_self=True):
                if name in io2.contents:
                    yield io2.contents[name]

class ZopeInterfaceFunction(model.Function):
    def docsources(self) -> Iterator[model.Documentable]:
        yield from super().docsources()
        yield from _inheritedDocsources(self)

class ZopeInterfaceAttribute(model.Attribute):
    def docsources(self) -> Iterator[model.Documentable]:
        yield from super().docsources()
        yield from _inheritedDocsources(self)

def addInterfaceInfoToScope(
        scope: Union[ZopeInterfaceClass, ZopeInterfaceModule],
        interfaceargs: Iterable[ast.expr],
        ctx: model.Documentable
        ) -> None:
    """Mark the given class or module as implementing the given interfaces.
    @param scope: class or module to modify
    @param interfaceargs: AST expressions of interface objects
    @param ctx: context in which C{interfaceargs} are looked up
    """
    for idx, arg in enumerate(interfaceargs):
        if isinstance(arg, ast.Starred):
            # We don't support star arguments at the moment.
            # But these are valid, so we shouldn't warn about them either.
            continue

        fullName = astbuilder.node2fullname(arg, ctx)
        if fullName is None:
            scope.report(
                'Interface argument %d does not look like a name' % (idx + 1),
                section='zopeinterface')
        else:
            scope.implements_directly.append(fullName)

def _handle_implemented(
        full_name: str,
        implementer: Union[ZopeInterfaceClass, ZopeInterfaceModule]
        ) -> None:
    """This is the counterpart to addInterfaceInfoToScope(), which is called
    during post-processing.
    """
    system = implementer.system
    iface = system.objForFullName(full_name)
    if iface is None:
        # The interface might have been reparented, in which case there will
        # be an alias at the original location; look for it using expandName().
        name_parts = full_name.split('.', 1)
        for root_obj in system.rootobjects:
            if root_obj.name == name_parts[0]:
                if len(name_parts) == 1:
                    iface = root_obj
                    break
                iface = system.objForFullName(root_obj.expandName(name_parts[1]))
                if iface is None:
                    implementer.report(
                        'Probable interface "%s" not found' % full_name,
                        section='zopeinterface')
                    return

    if isinstance(iface, ZopeInterfaceClass):
        if not iface.isinterface:
            implementer.report(
                'Probable interface "%s" not marked as such' % full_name,
                section='zopeinterface')
            iface.isinterface = True
            iface.kind = "Interface"
            iface.implementedby_directly = []
        iface.implementedby_directly.append(implementer)
    elif iface is not None:
        implementer.report(
            'Probable interface "%s" not detected as a class' % full_name,
            section='zopeinterface')

def addInterfaceInfoToModule(
        module: ZopeInterfaceModule,
        interfaceargs: Iterable[ast.expr]
        ) -> None:
    addInterfaceInfoToScope(module, interfaceargs, module)

def addInterfaceInfoToClass(
        cls: ZopeInterfaceClass,
        interfaceargs: Iterable[ast.expr],
        ctx: model.Documentable,
        implementsOnly: bool
        ) -> None:
    cls.implementsOnly = implementsOnly
    if implementsOnly:
        cls.implements_directly = []
    addInterfaceInfoToScope(cls, interfaceargs, ctx)


schema_prog = re.compile(r'zope\.schema\.([a-zA-Z_][a-zA-Z0-9_]*)')
interface_prog = re.compile(
    r'zope\.schema\.interfaces\.([a-zA-Z_][a-zA-Z0-9_]*)'
    r'|zope\.interface\.Interface')

def namesInterface(system: model.System, name: str) -> bool:
    if interface_prog.match(name):
        return True
    obj = system.objForFullName(name)
    if not isinstance(obj, ZopeInterfaceClass):
        return False
    return obj.isinterface

class ZopeInterfaceModuleVisitor(astbuilder.ModuleVistor):

    def funcNameFromCall(self, node: ast.Call) -> Optional[str]:
        while isinstance(node.func, ast.Call):
            node = node.func
        return astbuilder.node2fullname(node.func, self.builder.current)

    def _handleAssignmentInModule(self,
            target: str,
            annotation: ast.expr,
            expr: ast.expr,
            lineno: int
            ) -> None:
        super()._handleAssignmentInModule(
                target, annotation, expr, lineno)

        if not isinstance(expr, ast.Call):
            return
        funcName = self.funcNameFromCall(expr)
        if funcName is None:
            return
        ob = self.system.objForFullName(funcName)
        if isinstance(ob, ZopeInterfaceClass) and ob.isinterfaceclass:
            # TODO: Process 'bases' and '__doc__' arguments.
            interface = self.builder.pushClass(target, lineno)
            interface.isinterface = True
            interface.implementedby_directly = []
            interface.bases = []
            interface.baseobjects = []
            self.builder.popClass()
            self.newAttr = interface

    def _handleAssignmentInClass(self,
            target: str,
            annotation: ast.expr,
            expr: ast.expr,
            lineno: int
            ) -> None:
        super()._handleAssignmentInClass(target, annotation, expr, lineno)

        if not isinstance(expr, ast.Call):
            return
        attr = self.builder.current.contents.get(target)
        if attr is None:
            return
        funcName = self.funcNameFromCall(expr)
        if funcName is None:
            return

        if funcName == 'zope.interface.Attribute':
            attr.kind = 'Attribute'
            args = expr.args
            if len(args) == 1 and isinstance(args[0], ast.Str):
                attr.setDocstring(args[0])
            else:
                attr.report(
                    'definition of attribute "%s" should have docstring '
                    'as its sole argument' % attr.name,
                    section='zopeinterface')
        else:
            match = schema_prog.match(funcName)
            if match:
                attr.kind = match.group(1)
            else:
                cls = self.builder.system.objForFullName(funcName)
                if not (isinstance(cls, ZopeInterfaceClass) and cls.isschemafield):
                    return
                attr.kind = cls.name
            keywords = {arg.arg: arg.value for arg in expr.keywords}
            descrNode = keywords.get('description')
            if isinstance(descrNode, ast.Str):
                attr.setDocstring(descrNode)
            elif descrNode is not None:
                attr.report(
                    'description of field "%s" is not a string literal' % attr.name,
                    section='zopeinterface')

    def visit_Call(self, node: ast.Call) -> None:
        base = self.funcNameFromCall(node)
        if base is None:
            return
        meth = getattr(self, "visit_Call_" + base.replace('.', '_'), None)
        if meth is not None:
            meth(base, node)

    def visit_Call_zope_interface_moduleProvides(self, funcName: str, node: ast.Call) -> None:
        if not isinstance(self.builder.current, ZopeInterfaceModule):
            self.default(node)
            return

        addInterfaceInfoToModule(self.builder.current, node.args)

    def visit_Call_zope_interface_implements(self, funcName: str, node: ast.Call) -> None:
        cls = self.builder.current
        if not isinstance(cls, ZopeInterfaceClass):
            self.default(node)
            return
        addInterfaceInfoToClass(cls, node.args, cls,
                                funcName == 'zope.interface.implementsOnly')
    visit_Call_zope_interface_implementsOnly = visit_Call_zope_interface_implements

    def visit_Call_zope_interface_classImplements(self, funcName: str, node: ast.Call) -> None:
        parent = self.builder.current
        if not node.args:
            self.builder.system.msg(
                'zopeinterface',
                f'{parent.description}:{node.lineno}: '
                f'required argument to classImplements() missing',
                thresh=-1)
            return
        clsname = parent.expandName(astor.to_source(node.args[0]).strip())
        cls = self.system.allobjects.get(clsname)
        if not isinstance(cls, ZopeInterfaceClass):
            problem = 'not found' if cls is None else 'is not a class'
            self.builder.system.msg(
                'zopeinterface',
                f'{parent.description}:{node.lineno}: '
                f'argument "{clsname}" to classImplements() {problem}',
                thresh=-1)
            return
        addInterfaceInfoToClass(cls, node.args[1:], parent,
                                funcName == 'zope.interface.classImplementsOnly')
    visit_Call_zope_interface_classImplementsOnly = visit_Call_zope_interface_classImplements

    def visit_ClassDef(self, node: ast.ClassDef) -> Optional[ZopeInterfaceClass]:
        cls = super().visit_ClassDef(node)
        if cls is None:
            return None
        assert isinstance(cls, ZopeInterfaceClass)

        bases = [self.builder.current.expandName(base) for base in cls.bases]

        if 'zope.interface.interface.InterfaceClass' in bases:
            cls.isinterfaceclass = True

        if any(namesInterface(self.system, b) for b in cls.bases):
            cls.isinterface = True
            cls.kind = "Interface"
            cls.implementedby_directly = []

        for n, o in zip(cls.bases, cls.baseobjects):
            if schema_prog.match(n) or (o and o.isschemafield):
                cls.isschemafield = True

        for fn, args in cls.decorators:
            if fn == 'zope.interface.implementer':
                if args is None:
                    cls.report('@implementer requires arguments')
                    continue
                addInterfaceInfoToClass(cls, args, cls.parent, False)

        return cls


class ZopeInterfaceASTBuilder(astbuilder.ASTBuilder):
    ModuleVistor = ZopeInterfaceModuleVisitor


class ZopeInterfaceSystem(model.System):
    Module = ZopeInterfaceModule
    Class = ZopeInterfaceClass
    Function = ZopeInterfaceFunction
    Attribute = ZopeInterfaceAttribute
    defaultBuilder = ZopeInterfaceASTBuilder

    def postProcess(self) -> None:
        super().postProcess()

        for mod in self.objectsOfType(ZopeInterfaceModule):
            for implemented in mod.implements_directly:
                _handle_implemented(implemented, mod)

        for cls in self.objectsOfType(ZopeInterfaceClass):
            for implemented in cls.implements_directly:
                _handle_implemented(implemented, cls)
