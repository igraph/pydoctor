
Customize Output
================

Include custom HTML
-------------------

They are 3 placeholders designed to be overwritten to include custom HTML and CSS into the pages.

- ``header.html``: at the very beginning of the body
- ``subheader.html``: after the main header, before the page title
- ``extra.css``: extra CSS sheet for layout customization

To override a placeholder, write your custom HTML or CSS files to a directory
and use the following option::

  --template-dir=./pydoctor_templates

.. note::

  If you want more customization, you can override the defaults
  HTML, CSS and JS templates in
  `pydoctor/templates <https://github.com/twisted/pydoctor/tree/master/pydoctor/templates>`_
  with the same method.

  HTML templates have their own versionning system and warnings will be triggered if oudated custom template are used.

.. admonition:: Example

    See this `sample template <https://github.com/twisted/pydoctor/tree/master/docs/sample_template>`_
    output `here <custom_template_demo/pydoctor.html>`_.

Use a custom system class
-------------------------

You can subclass the :py:class:`pydoctor.zopeinterface.ZopeInterfaceSystem`
and pass your custom class dotted name with the following argument::

  --system-class=mylib._pydoctor.CustomSystem

System class allows you to dynamically show/hide classes or methods.
This is also used by the Twisted project to handle deprecation.

See the :py:class:`twisted:twisted.python._pydoctor.TwistedSystem` custom class documentation.
Navigate to the source code for a better overview.

Use a custom writer class
-------------------------

You can subclass the :py:class:`pydoctor.templatewriter.TemplateWriter`
and pass your custom class dotted name with the following argument::


  --html-class=mylib._pydoctor.CustomTemplateWriter

.. warning:: Pydoctor does not have a stable API yet. Code customization is prone
    to break in future versions.
