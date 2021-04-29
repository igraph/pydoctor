"""Render pydoctor data as HTML."""
from typing import Iterable, Optional, Dict, overload, TYPE_CHECKING
if TYPE_CHECKING:
    from typing_extensions import Protocol, runtime_checkable
else:
    Protocol = object
    def runtime_checkable(f):
        return f
import abc
from pathlib import Path
import warnings
from xml.dom import minidom

from twisted.web.iweb import ITemplateLoader
from twisted.web.template import TagLoader, XMLString, Element, tags

from pydoctor.model import System, Documentable

DOCTYPE = b'''\
<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN"
          "DTD/xhtml1-strict.dtd">
'''

def parse_xml(text: str) -> minidom.Document:
    """
    Create a L{minidom} representaton of the XML string.
    """
    try:
        return minidom.parseString(text)
    except Exception as e:
        raise ValueError(f"Failed to parse template as XML: {e}") from e

class UnsupportedTemplateVersion(Exception):
    """Raised when custom template is designed for a newer version of pydoctor"""
    pass

@runtime_checkable
class IWriter(Protocol):
    """
    Interface class for pydoctor output writer.
    """

    @overload
    def __init__(self, htmloutput: str) -> None: ...
    @overload
    def __init__(self, htmloutput: str, template_lookup: 'TemplateLookup') -> None: ...

    def prepOutputDirectory(self) -> None:
        """
        Called first.
        """

    def writeSummaryPages(self, system: System) -> None:
        """
        Called second.
        """

    def writeIndividualFiles(self, obs:Iterable[Documentable]) -> None:
        """
        Called last.
        """


class Template(abc.ABC):
    """
    Represents a pydoctor template file.

    It holds references to template information.

    It's an additionnal level of abstraction to hook to the
    rendering system, it stores the loader object that
    is going to be reused for each output file using this template.

    Use L{Template.fromfile} to create Templates.

    @see: L{TemplateLookup}
    """

    def __init__(self, name: str, text: str):
        self.name = name
        """Template filename"""

        self.text = text
        """Template text: contents of the template file."""

    TEMPLATE_FILES_SUFFIX = ('.html', '.css', '.js')

    @classmethod
    def fromfile(cls, path: Path) -> Optional['Template']:
        """
        Create a concrete template object.
        Type depends on the file extension.

        Warns if the template cannot be created.

        @param path: A L{Path} that should point to a HTML, CSS or JS file.
        @returns: The template object or C{None} if file is invalid.
        """
        if path.suffix.lower() in cls.TEMPLATE_FILES_SUFFIX:
            try:
                with path.open('r', encoding='utf-8') as fobj:
                    text = fobj.read()
            except IOError as e:
                warnings.warn(f"Cannot load Template: {path.as_posix()}. I/O error: {e}")
            else:
                if path.suffix.lower() == '.html':
                    return _HtmlTemplate(name=path.name, text=text)
                else:
                    return _StaticTemplate(name=path.name, text=text)
        else:
            warnings.warn(f"Cannot create Template: {path.as_posix()} is not recognized as template file. "
                f"Template files must have one of the following extensions: {', '.join(cls.TEMPLATE_FILES_SUFFIX)}")
        return None

    def is_empty(self) -> bool:
        """
        Does this template contain nothing except whitespace?
        Empty templates will not be rendered.
        """
        return len(self.text.strip()) == 0

    @abc.abstractproperty
    def version(self) -> int:
        """
        Template version, C{-1} if no version.

        HTML Templates should have a version identifier as follow::

            <meta name="pydoctor-template-version" content="1" />

        This is always C{-1} for CSS and JS templates.
        """
        raise NotImplementedError()

    @abc.abstractproperty
    def loader(self) -> Optional[ITemplateLoader]:
        """
        Object used to render the final file.

        For HTML templates, this is a L{ITemplateLoader}.

        For CSS and JS templates, this is C{None}
        because there is no rendering to do, it's already the final file.
        """
        raise NotImplementedError()

class _StaticTemplate(Template):
    """
    Static template: no rendering, will be copied as is to build directory.

    For CSS and JS templates.
    """
    @property
    def version(self) -> int:
        return -1
    @property
    def loader(self) -> None:
        return None

class _HtmlTemplate(Template):
    """
    HTML template that works with the Twisted templating system
    and use L{xml.dom.minidom} to parse the C{pydoctor-template-version} meta tag.
    """
    def __init__(self, name: str, text: str):
        super().__init__(name=name, text=text)
        if self.is_empty():
            self._dom: Optional[minidom.Document] = None
            self._version = -1
            self._loader: ITemplateLoader = TagLoader(tags.transparent)
        else:
            self._dom = parse_xml(self.text)
            self._version = self._extract_version(self._dom, self.name)
            self._loader = XMLString(self._dom.toxml())

    @property
    def version(self) -> int:
        return self._version
    @property
    def loader(self) -> ITemplateLoader:
        return self._loader

    @staticmethod
    def _extract_version(dom: minidom.Document, template_name: str) -> int:
        # If no meta pydoctor-template-version tag found,
        # it's most probably a placeholder template.
        version = -1
        for meta in dom.getElementsByTagName("meta"):
            if meta.getAttribute("name") != "pydoctor-template-version":
                continue

            # Remove the meta tag as soon as found
            meta.parentNode.removeChild(meta)

            if not meta.hasAttribute("content"):
                warnings.warn(f"Could not read '{template_name}' template version: "
                    f"the 'content' attribute is missing")
                continue

            version_str = meta.getAttribute("content")

            try:
                version = int(version_str)
            except ValueError:
                warnings.warn(f"Could not read '{template_name}' template version: "
                        "the 'content' attribute must be an integer")
            else:
                break

        return version

class TemplateLookup:
    """
    The L{TemplateLookup} handles the HTML template files locations.
    A little bit like C{mako.lookup.TemplateLookup} but more simple.

    The location of the files depends wether the users set a template directory
    with the option C{--template-dir}, custom files with matching names will be
    loaded if present.

    This object allow the customization of any templates, this can lead to warnings
    when upgrading pydoctor, then, please update your template.

    @note: The HTML templates versions are independent of the pydoctor version
           and are idependent from each other.

    @see: L{Template}
    """

    _default_template_dir = 'templates'

    def __init__(self) -> None:
        """
        Init L{TemplateLookup} with templates in C{pydoctor/templates}.
        This loads all templates into the lookup C{_templates} dict.
        """

        # Relative path from here is: ../templates
        default_template_dir = Path(__file__).parent.parent.joinpath(self._default_template_dir)

        self._templates: Dict[str, Template] = {
            t.name: t
            for t in (Template.fromfile(f) for f in default_template_dir.iterdir())
            if t
            }

        self._default_templates = self._templates.copy()


    def add_template(self, template: Template) -> None:
        """
        Add a custom template to the lookup. The custom template override the default.

        Compare the passed Template version with default template,
        issue warnings if template are outdated.

        @raises UnsupportedTemplateVersion: If the custom template is designed for a newer version of pydoctor.
        """

        try:
            default_version = self._default_templates[template.name].version
        except KeyError:
            warnings.warn(f"Invalid template filename '{template.name}'. "
                f"Valid filenames are: {list(self._templates)}")
        else:
            template_version = template.version
            if default_version and template_version != -1:
                if template_version < default_version:
                    warnings.warn(f"Your custom template '{template.name}' is out of date, "
                                    "information might be missing. "
                                   "Latest templates are available to download from our github." )
                elif template_version > default_version:
                    raise UnsupportedTemplateVersion(f"It appears that your custom template '{template.name}' "
                                        "is designed for a newer version of pydoctor."
                                        "Rendering will most probably fail. Upgrade to latest "
                                        "version of pydoctor with 'pip install -U pydoctor'. ")
            self._templates[template.name] = template

    def add_templatedir(self, dir: Path) -> None:
        """
        Scan a directory and add all templates in the given directory to the lookup.
        """
        for path in dir.iterdir():
            template = Template.fromfile(path)
            if template:
                self.add_template(template)

    def get_template(self, filename: str) -> Template:
        """
        Lookup a template based on its filename.

        Return the custom template if provided, else the default template.

        @param filename: File name, (ie 'index.html')
        @return: The Template object
        @raises KeyError: If no template file is found with the given name
        """
        try:
            t = self._templates[filename]
        except KeyError as e:
            raise KeyError(f"Cannot find template '{filename}' in template lookup: {self}. "
                f"Valid filenames are: {list(self._templates)}") from e
        return t

    def get_loader(self, filename: str) -> ITemplateLoader:
        """
        Lookup a HTML template loader based on its filename.

        @raises ValueError: If the template loader is C{None}.
        """
        template = self.get_template(filename)
        if template.loader is None:
            raise ValueError(f"Failed to get loader of template '{filename}' (template.loader is None)")
        return template.loader

    @property
    def templates(self) -> Iterable[Template]:
        """
        All templates that can be looked up.
        For each name, the custom template will be included if it exists,
        otherwise the default template.
        """
        return self._templates.values()

class TemplateElement(Element, abc.ABC):
    """
    Renderable element based on a template file.
    """

    filename: str = NotImplemented
    """
    Associated template filename.
    """

    @classmethod
    def lookup_loader(cls, template_lookup: TemplateLookup) -> ITemplateLoader:
        """
        Lookup the element L{ITemplateLoader} with the the C{TemplateLookup}.
        """
        return template_lookup.get_loader(cls.filename)

from pydoctor.templatewriter.writer import TemplateWriter
__all__ = ["TemplateWriter"] # re-export as pydoctor.templatewriter.TemplateWriter
