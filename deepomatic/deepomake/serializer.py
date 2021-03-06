import os, sys
import copy
import yaml
from collections import OrderedDict
from deepomatic.deepomake.common import DMakeException
import deepomatic.deepomake.common as common

# Define the base class for YAML2PipelineSerializer
# If using Python3, we can keep track of the order of the field
# in order to generate a proper doc.
if sys.version_info >= (3,0):
    from deepomatic.deepomake.python_3x import BaseYAML2PipelineSerializer
else:
    from deepomatic.deepomake.python_2x import BaseYAML2PipelineSerializer

# Custom Exceptions
class ValidationError(Exception):
    pass

class WrongType(ValidationError):
    pass

# Serializers
class FieldSerializer(object):
    def __init__(self,
            data_type,
            optional = False,
            default = None,
            blank = False,
            child = None,
            post_validation = lambda x: x,
            child_path_only = False,
            check_path = True,
            executable = False,
            no_slash_no_space = False,
            help_text = "",
            example = None):
        self.allowed_types = ["bool", "int", "path", "dir", "string", "array", "dict"]

        if not isinstance(data_type, list):
            data_type = [data_type]
        for t in data_type:
            assert(isinstance(t, YAML2PipelineSerializer) or isinstance(t, FieldSerializer) or t in self.allowed_types)
            if t == "array" or t == "dict":
                if child in self.allowed_types:
                    child = FieldSerializer(child, blank = True)
                else:
                    assert(isinstance(child, FieldSerializer) or isinstance(child, YAML2PipelineSerializer))

        if default is not None:
            optional = True

        self.data_type = data_type
        self.optional = optional
        self.default = default
        self.blank = blank
        self.post_validation = post_validation
        self.child_path_only = child_path_only
        self.check_path = check_path
        self.executable = executable
        self.no_slash_no_space = no_slash_no_space
        self.help_text = help_text
        self.example = example

        self.child = child
        self.value = None

    def _validate_(self, path, data):
        if data is None:
            if not self.optional:
                raise ValidationError("got 'Null', expected a value of type %s" % (" -OR-\n".join([str(t) for t in self.data_type])))
            else:
                data = copy.deepcopy(self.default)
        else:
            ok = False
            err = []
            for t in self.data_type:
                if isinstance(t, YAML2PipelineSerializer) or isinstance(t, FieldSerializer):
                    try:
                        data = t._validate_(path, data)
                        ok = True
                        break
                    except ValidationError as e:
                        err.append(str(e).replace('\n', '\n  '))
                        continue
                else:
                    try:
                        data = self._validate_type_(path, t, data)
                        ok = True
                        break
                    except WrongType as e:
                        err.append(str(e))
                        continue
            if not ok:
                if len(err) == 1:
                    raise ValidationError(err[0])
                else:
                    raise ValidationError("The error is one of the followings:\n- " + ("\n- ".join(err)))
        self.value = self.post_validation(data)
        return self.value

    def _value_(self):
        return self.value

    def _default_(self):
        if self.default is None:
            raise ValidationError('Not default value provided.')
        return self.default

    def _validate_type_(self, path, data_type, data):
        if data_type == "bool":
            if not isinstance(data, bool):
                raise WrongType("Expecting bool")
            return data
        elif data_type == "int":
            if isinstance(data, int) or isinstance(data, float):
                data = int(data)
            if not isinstance(data, int):
                raise WrongType("Expecting int")
            return str(data)
        elif data_type == "string":
            if isinstance(data, int) or isinstance(data, float):
                data = str(data)
            if not common.is_string(data):
                raise WrongType("Expecting string")
            if not self.blank and data == "":
                raise WrongType("Expecting non-blank string")
            if self.no_slash_no_space:
                for c in ['/', ' ']:
                    if data.find(c) >= 0:
                        raise ValidationError("Character '%s' not allowed" % c)
            return data
        elif data_type == "path" or data_type == "dir":
            if not common.is_string(data):
                raise WrongType("Expecting string")
            if len(data) > 0 and data[0] == '/':
                data = data[1:]
                full_path = data
                if self.child_path_only:
                    if full_path.startswith(path):
                        data = data[len(path)]
                        if len(data) > 0 and data[0] == '/':
                            data = data[1:]
                    else:
                        raise WrongType("Path must be sub-paths to deepomake file for this field.")
            else:
                full_path = os.path.join(path, data)
                if not self.child_path_only:
                    data = full_path
            data = os.path.normpath(data)
            if data.startswith("../"):
                raise WrongType("Trying to access a parent directory is forbidden")
            if self.check_path:
                if data_type == "path":
                    if not os.path.isfile(full_path):
                        raise WrongType("Could not find file: %s" % data)
                    if self.executable and not os.access(full_path, os.X_OK):
                        raise WrongType("The file must be executable: %s" % full_path)
                else:
                    if not os.path.isdir(full_path):
                        raise WrongType("Could not find directory: %s" % data)
            return data
        elif data_type == "array":
            if not isinstance(data, list):
                raise WrongType("Expecting array")
            valid_data = []
            for d in data:
                child = copy.deepcopy(self.child)
                valid_data.append(child._validate_(path, d))
            return valid_data
        elif data_type == "dict":
            if not isinstance(data, dict):
                raise WrongType("Expecting dict")
            valid_data = {}
            for k, d in data.items():
                child = copy.deepcopy(self.child)
                try:
                    valid_data[k] = child._validate_(path, d)
                except ValidationError as e:
                    raise ValidationError("Error with field '%s': %s" % (k, str(e)))
            return valid_data
        else:
            raise DMakeException("Unkown data type: %s" % data_type)

    def _serialize_(self, *args, **kwargs):
        if isinstance(self.value, list):
            for f in self.value:
                f._serialize_(*args, **kwargs)
        else:
            raise DMakeException("Do not known how to serialize non array field")

    # # Returns a list of tuple (padded_yaml, comment)
    # def generate_doc(self):
    #     comment = "%s" % self.help_text

    #     value = None
    #     if self.example:
    #         value = self.example
    #     elif self.default:
    #         value = self.default

    #     if self.default is not None:
    #         if comment:
    #             comment += " "
    #         default = self.default
    #         if isinstance(default, bool):
    #             default = "true" if default else "false"
    #         if common.is_string(default):
    #             default = "'%s'" % default
    #         comment += "(defaults to %s)" % str(default)

    #     options = []
    #     for t in self.data_type:
    #         v = value
    #         if isinstance(t, YAML2PipelineSerializer):
    #             _, lines = t.generate_doc()
    #             options.append(lines)
    #         elif t == "dict":
    #             _, sub_lines = self.child.generate_doc()
    #             first = sub_lines[0]
    #             rest = sub_lines[1:]
    #             lines = [("", comment), ("any_key: " + first[0], "")] + rest
    #             options.append(lines)
    #         elif t == "array":
    #             _, sub_lines = self.child.generate_doc()
    #             first = sub_lines[0]
    #             rest = sub_lines[1:]
    #             lines = [("", comment), ("- " + first[0], first[1])]
    #             for l, c in rest:
    #                 if l[0] == '!':
    #                     l = '|' + l[1:]
    #                     padding = 0
    #                 else:
    #                     padding = 4
    #                 lines.append((" " * padding + l, c))
    #             options.append(lines)
    #         elif t == "int":
    #             if v is None:
    #                 v = "1"
    #             lines = [(v, comment)]
    #             options.append(lines)
    #         elif t == "path" or t == "dir":
    #             path_str = "path" if t == "path" else "directory"
    #             if self.child_path_only:
    #                 if comment:
    #                     comment += " "
    #                 comment += "(relative %s only)" % path_str
    #             if v is None:
    #                 if self.child_path_only:
    #                     v = "some/relative/%s/example" % path_str
    #                 else:
    #                     v = "some/%s/example" % path_str
    #             lines = [(v, comment)]
    #             options.append(lines)
    #         elif t == "string":
    #             if v is None or not common.is_string(v):
    #                 v = "Some string"
    #             lines = [(v, comment)]
    #             options.append(lines)
    #         elif t == "bool":
    #             if v is None or not (common.is_string(v) or isinstance(v, bool)):
    #                 v = "false"
    #             elif isinstance(v, bool):
    #                 v = "true" if v else "false"
    #             lines = [(v, comment)]
    #             options.append(lines)
    #         else:
    #             raise Exception("Unknown type: %s" % str(t))

    #     lines = options[0]
    #     if len(options) > 1:
    #         for opt in options[1:]:
    #             first = opt[0]
    #             rest  = opt[1:]
    #             lines.append(('!   ' + first[0], "-OR- " + first[1]))
    #             lines += rest
    #     return self.optional, lines

    def get_type_name(self, obj, padding, is_plural = False):
        if isinstance(obj, FieldSerializer) and len(obj.data_type) == 1:
            return obj.get_type_name(obj.data_type[0], padding, is_plural)

        doc_string = None
        if isinstance(obj, YAML2PipelineSerializer) or isinstance(obj, FieldSerializer):
            _, _, doc_string = obj.generate_doc(padding)
            type_str = 'object'
            help_text = ('%s with the following fields:' % ('objects' if is_plural else 'an object'))
        elif obj == "dict":
            type_str, help_text, doc_string = self.get_type_name(self.child, padding, True)
            type_str = 'free style object'
            help_text = ('%s of ' % ('dictionnaries' if is_plural else 'a dictionnary')) + help_text
        elif obj == "array":
            type_str, help_text, doc_string = self.get_type_name(self.child, padding, True)
            type_str = 'array\\<%s\\>' % type_str
            help_text = ('%s of ' % ('arrays' if is_plural else 'an array')) + help_text
        elif obj == "int":
            type_str = 'int'
            help_text = 'integers' if is_plural else 'an integer'
        elif obj == "path":
            type_str = 'file path'
            help_text = 'file paths' if is_plural else 'a file path'
        elif obj == "dir":
            type_str = 'directory path'
            help_text = 'directories' if is_plural else 'a directory'
        elif obj == "string":
            type_str = 'string'
            help_text = 'strings' if is_plural else 'a string'
        elif obj == "bool":
            type_str = 'boolean'
            help_text = 'booleans' if is_plural else 'a boolean'
        else:
            raise Exception("Unknown type: %s" % str(obj))

        return type_str, help_text, doc_string

    # Returns a tuple (optional, infos, help_text, doc_string)
    def generate_doc(self, padding):
        infos = []

        help_text = self.help_text
        if len(help_text) > 0 and help_text[-1] != '.':
            help_text += '.'

        if len(self.data_type) == 1:
            type_str, ht, doc_string = self.get_type_name(self.data_type[0], padding)
        else:
            type_str = 'mixed'
            help_text += ' It can be one of the followings:'
            doc_string = []
            for t in self.data_type:
                tn, ht, ds = self.get_type_name(t, padding + 4)
                if isinstance(t, FieldSerializer) and t.help_text is not None:
                    ht += " " + t.help_text
                doc_string.append(('%s- ' % (' ' * padding)) + ht)
                if ds is not None:
                    doc_string.append(ds)
            doc_string = '\n'.join(doc_string)

        # Add the type
        infos.append(type_str)

        if self.default is not None:
            infos.append('default = %s' % yaml.dump(self.default, default_flow_style = True).strip())

        return infos, help_text, doc_string

    def generate_example(self):
        if self.example is not None:
            return self.example
        elif self.default:
            return self.default

        value = None
        for t in self.data_type:
            if isinstance(t, YAML2PipelineSerializer) or isinstance(t, FieldSerializer):
                return t.generate_example()
            elif t == "dict":
                value = {'any_key': self.child.generate_example()}
            elif t == "array":
                value = [self.child.generate_example()]
            elif value is None:
                if t == "int":
                    value = "1"
                elif t == "path" or t == "dir":
                    path_str = "path" if t == "path" else "directory"
                    if self.child_path_only:
                        value = "some/relative/%s/example" % path_str
                    else:
                        value = "some/%s/example" % path_str
                elif t == "string":
                    value = "Some string"
                elif t == "bool":
                    value = "true"
                else:
                    raise DMakeException("Unknown type: %s" % str(t))
        return value

class YAML2PipelineSerializer(BaseYAML2PipelineSerializer):
    def __init__(self, optional = False, help_text = ""):
        self.__optional__  = optional
        self.__help_text__ = help_text
        self.__has_value__ = False

        if sys.version_info >= (3,0):
            fields_list = self.__fields_order__
        else:
            fields_list = dir(self)

        fields = OrderedDict()
        for k in fields_list:
            if k.startswith('_'):
                continue
            v = getattr(self, k)
            if isinstance(v, FieldSerializer) or isinstance(v, YAML2PipelineSerializer):
                fields[k] = copy.deepcopy(v)
        self.__fields__ = fields

    def _validate_(self, path, data):
        if data is None:
            if self.__optional__:
                return None
            data = {}
        for name, serializer in self.__fields__.items():
            try:
                serializer._validate_(path, data[name] if name in data else None)
            except ValidationError as e:
                raise ValidationError("Error with field '%s': %s" % (name, str(e)))
        for key in data:
            if not common.is_string(key):
                raise ValidationError("Expected a field name, got: '%s'" % str(key))
            if key not in self.__fields__:
                raise ValidationError("Unexpected field '%s'" % key)
        self.__has_value__ = True
        return self

    def __getattribute__(self, key):
        try:
            fields = object.__getattribute__(self, '__fields__')
        except AttributeError:
            return object.__getattribute__(self, key)
        has_data = object.__getattribute__(self, '__has_value__')
        if key in fields:
            if isinstance(fields[key], FieldSerializer):
                if has_data:
                    return fields[key]._value_()
                else:
                    raise DMakeException("No data has been validated yet, cannot access field '%s'" % key)
            else:
                return fields[key]
        else:
            return object.__getattribute__(self, key)

    def has_value(self):
        return self.__has_value__

    def _value_(self):
        if not self.__has_value__:
            return None
        value = {}
        for k, v in self.__fields__.items():
            value[k] = v._value_()
        return value

    def default_value(self):
        value = {}
        for k, v in self.__fields__.items():
            try:
                value[k] = v._default_()
            except ValidationError as e:
                raise DMakeException("Field '%s': %s" % (k, str(e)))
        return value

    # # Returns a tuple (optional, [(padded_yaml, comment)])
    # def generate_doc(self):
    #     comment = "%s" % self.__help_text__
    #     lines = [("", comment)]
    #     for key, field in self.__fields__.items():
    #         optional, sub_lines = field.generate_doc()
    #         first = sub_lines[0]
    #         rest = sub_lines[1:]
    #         k = key if not optional else "[%s]" % key
    #         lines.append((k + ": " + str(first[0]), first[1]))
    #         for l, c in rest:
    #             if l[0] == '!': # little hack: otherwise no padding at all for lines starting with |
    #                 l = '|' + l[1:]
    #                 padding = 0
    #             else:
    #                 padding = 4
    #             lines.append((" " * padding + l, c))
    #     return self.__optional__, lines

    # Returns a tuple (optional, infos, help_text, doc_string)
    def generate_doc(self, padding = 0):
        lines = []
        for key, field in self.__fields__.items():
            infos, help_text, doc_string = field.generate_doc(padding + 4)

            infos = ', '.join(copy.deepcopy(infos))
            if infos:
                infos = ' *(%s)*' % infos

            lines.append('%s- **%s**%s: %s' % (' ' * padding, key, infos, help_text))
            if doc_string is not None:
                lines.append(doc_string)

        help_text = self.__help_text__
        if len(help_text) > 0 and help_text[-1] != '.':
            help_text += '.'
        help_text += ' It must be an object with the following fields:'

        doc_string = '\n'.join(lines)

        infos = ['object']
        if self.__optional__:
            infos.append('optional')
        return infos, help_text, doc_string

    def generate_example(self):
        ex = OrderedDict()
        for key, field in self.__fields__.items():
            value = field.generate_example()
            if value == "":
                continue
            ex[key] = value
        return ex
