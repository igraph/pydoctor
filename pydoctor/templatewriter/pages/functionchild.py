from twisted.web.template import renderer, tags

from pydoctor.templatewriter.pages import format_decorators, signature
from pydoctor.templatewriter import TemplateElement, util

class FunctionChild(TemplateElement):

    filename = 'function-child.html'

    def __init__(self, docgetter, ob, extras, loader):
        super().__init__(loader)
        self.docgetter = docgetter
        self.ob = ob
        self._functionExtras = extras

    @renderer
    def class_(self, request, tag):
        class_ = util.css_class(self.ob)
        if self.ob.parent is not self.ob:
            class_ = 'base' + class_
        return class_

    @renderer
    def functionAnchor(self, request, tag):
        return self.ob.fullName()

    @renderer
    def shortFunctionAnchor(self, request, tag):
        return self.ob.name

    @renderer
    def decorator(self, request, tag):
        return list(format_decorators(self.ob))

    @renderer
    def functionDef(self, request, tag):
        def_stmt = 'async def' if self.ob.is_async else 'def'
        name = self.ob.name
        if name.endswith('.setter') or name.endswith('.deleter'):
            name = name[:name.rindex('.')]
        return [
            tags.span(def_stmt, class_='py-keyword'), ' ',
            tags.span(name, class_='py-defname'), signature(self.ob), ':'
            ]

    @renderer
    def sourceLink(self, request, tag):
        if self.ob.sourceHref:
            return tag.fillSlots(sourceHref=self.ob.sourceHref)
        else:
            return ()

    @renderer
    def functionExtras(self, request, tag):
        return self._functionExtras

    @renderer
    def functionBody(self, request, tag):
        return self.docgetter.get(self.ob)

    @renderer
    def functionDeprecated(self, request, tag):
        if hasattr(self.ob, "_deprecated_info"):
            return (tags.div(self.ob._deprecated_info, role="alert", class_="deprecationNotice alert alert-warning"),)
        else:
            return ()
