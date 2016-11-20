# -*- coding: utf-8 -*-

"""
Copyright (C) 2016, Zato Source s.r.o. https://zato.io

Licensed under LGPLv3, see LICENSE.txt for terms and conditions.
"""

from __future__ import absolute_import, division, print_function, unicode_literals

# Bunch
from bunch import Bunch, bunchify

# docformatter
from docformatter import format_docstring

# Zato
from zato.common import SIMPLE_IO
from zato.server.service.reqresp.sio import AsIs, SIO_TYPE_MAP, is_bool, is_int

# ################################################################################################################################

_sio_attrs = ('input_required', 'output_required', 'input_optional', 'output_optional')
_service_attrs = ('namespace', 'all')

# ################################################################################################################################

class Config(object):
    def __init__(self):
        self.is_module_level = True
        self.ns = ''
        self.services = []

# ################################################################################################################################

class Docstring(object):
    def __init__(self):
        self.summary = ''
        self.description = ''
        self.full = ''

# ################################################################################################################################

class SimpleIO(object):
    def __init__(self, api_spec_info):
        self.input_required = api_spec_info.param_list.input_required
        self.output_required = api_spec_info.param_list.output_required
        self.input_optional = api_spec_info.param_list.input_optional
        self.output_optional = api_spec_info.param_list.output_optional
        self.request_elem = api_spec_info.request_elem
        self.response_elem = api_spec_info.response_elem
        self.spec_name = api_spec_info.name

    def to_bunch(self):
        out = Bunch()
        for name in _sio_attrs + ('request_elem', 'response_elem', 'spec_name'):
            out[name] = getattr(self, name)

        return out

# ################################################################################################################################

class ServiceInfo(object):
    """ Contains information about a service basing on which documentation is generated.
    """
    def __init__(self, name, service_class):
        self.name = name
        self.service_class = service_class
        self.config = Config()
        self.simple_io = {}
        self.docstring = Docstring()
        self.invokes = []
        self.invoked_by = []
        self.parse()

# ################################################################################################################################

    def parse(self):
        self.set_config()
        #self.set_simple_io()
        self.set_summary_desc()

# ################################################################################################################################

    def _add_services_from_invokes(self):
        """ Populates the list of services that this services invokes.

        class MyService(Service):
          invokes = 'foo'

        class MyService(Service):
          invokes = ['foo', 'bar']
        """
        invokes = getattr(self.service_class, 'invokes', None)
        if invokes:
            if isinstance(invokes, basestring):
                self.invokes.append(invokes)
            else:
                if isinstance(invokes, (list, tuple)):
                    self.invokes.extend(list(invokes))

# ################################################################################################################################

    def _add_simple_io(self):
        sio = getattr(self.service_class, 'SimpleIO', None)

        if sio:
            for api_spec_info in SIO_TYPE_MAP:

                _api_spec_info = Bunch()
                _api_spec_info.name = api_spec_info.name
                _api_spec_info.param_list = Bunch()
                _api_spec_info.request_elem = getattr(sio, 'request_elem', None)
                _api_spec_info.response_elem = getattr(sio, 'response_elem', None)

                for param_list_name in _sio_attrs:
                    _param_list = []
                    param_list = getattr(sio, param_list_name, [])

                    for param in param_list:
                        param_name = param if isinstance(param, basestring) else param.name
                        _param_info = Bunch()
                        _param_info.name = param_name

                        if isinstance(param, AsIs):
                            type_info = api_spec_info.DEFAULT

                        elif is_bool(param, param_name, SIMPLE_IO.BOOL_PARAMETERS.SUFFIXES):
                            type_info = api_spec_info.BOOLEAN

                        elif is_int(param_name, SIMPLE_IO.INT_PARAMETERS.VALUES, SIMPLE_IO.INT_PARAMETERS.SUFFIXES):
                            type_info = api_spec_info.INTEGER

                        else:
                            try:
                                type_info = api_spec_info.map[param.__class__]
                            except KeyError:
                                type_info = api_spec_info.DEFAULT
    
                        _param_info.type, _param_info.subtype = type_info
                        _param_list.append(_param_info)

                    _api_spec_info.param_list[param_list_name] = _param_list

                self.simple_io[_api_spec_info.name] = SimpleIO(_api_spec_info).to_bunch()

# ################################################################################################################################

    def set_config(self):
        self._add_services_from_invokes()
        self._add_simple_io()

# ################################################################################################################################

    def set_summary_desc(self):

        doc = self.service_class.__doc__
        if not doc:
            return

        split = doc.splitlines()
        summary = split[0]

        # format_docstring expects an empty line between summary and description
        if len(split) > 1:
            _doc = []
            _doc.append(split[0])
            _doc.append('')
            _doc.extend(split[1:])
            doc = '\n'.join(_doc)

        # This gives us the full docstring out of which we need to extract description alone.
        full_docstring = format_docstring('', '"{}"'.format(doc), post_description_blank=False)
        full_docstring = full_docstring.lstrip('"""').rstrip('"""')
        description = full_docstring.splitlines()

        # If there are multiple lines and the second one is empty this means it is an indicator of a summary to follow.
        if len(description) > 1 and not description[1]:
            description = '\n'.join(description[2:])
        else:
            description = ''

        # docformatter.normalize_summary adds superfluous period at end docstring.
        if full_docstring:
            if description and full_docstring[-1] == '.' and full_docstring[-1] != description[-1]:
                full_docstring = full_docstring[:-1]

            if summary and full_docstring[-1] == '.' and full_docstring[-1] != summary[-1]:
                full_docstring = full_docstring[:-1]

        self.docstring.summary = summary.strip()
        self.docstring.description = description
        self.docstring.full = full_docstring.rstrip()

# ################################################################################################################################

class Generator(object):
    def __init__(self, service_store_services, filter=None):
        self.service_store_services = service_store_services
        self.filter = filter
        self.services = {}

        # Service name -> list of services this service invokes
        self.invokes = {}

        # Service name -> list of services this service is invoked by
        self.invoked_by = {}

    def get_info(self, ignore_prefix='zato'):
        """ Returns a list of dicts containing metadata about services in the scope required to generate docs and API clients.
        """
        self.parse(ignore_prefix)

        out = []
        for name in sorted(self.services):

            if self.filter and name != self.filter:
                continue

            info = self.services[name]
            item = Bunch()

            item.name = info.name
            item.docs = Bunch()
            item.docs.summary = info.docstring.summary
            item.docs.description = info.docstring.description
            item.docs.full = info.docstring.full
            item.invokes = sorted(info.invokes)
            item.invoked_by = sorted(info.invoked_by)
            item.simple_io = info.simple_io

            out.append(item.toDict())

        return out

# ################################################################################################################################

    def parse(self, ignore_prefix):

        for impl_name, details in self.service_store_services.iteritems():
            if not impl_name.startswith(ignore_prefix):
                details = bunchify(details)
                info = ServiceInfo(details['name'], details['service_class'])
                self.services[info.name] = info

        for name, info in self.services.iteritems():
            self.invokes[name] = info.invokes

        for source, targets in self.invokes.iteritems():
            for target in targets:
                sources = self.invoked_by.setdefault(target, [])
                sources.append(source)

        for name, info in self.services.iteritems():
            info.invoked_by = self.invoked_by.get(name, [])

# ################################################################################################################################
