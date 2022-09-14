# coding=utf-8
# Copyright 2022 Google LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Helper functions and types related to Fiddle."""

import dataclasses
from typing import overload, TypeVar, Callable, Any, Union, Optional, Collection

import fiddle as fdl
from fiddle import daglish
from fiddle import tagging
from fiddle.experimental import auto_config
from fiddle.experimental import dataclasses as fdl_dataclasses
from fiddle.experimental.dataclasses import field as fdl_field

fdl_field = fdl_dataclasses.field
TagOrTags = Union[type(fdl.Tag), Collection[type(fdl.Tag)]]
T = TypeVar('T')


class DoNotBuild(fdl.Tag):
  """Tag specifying that a value should not be built by `fdl.build`.

  This is used for template fields, which should contain `fdl.Buildable` objects
  even after they are built.
  """


def sub_field(
    field_type: Callable[..., Any], tags: Optional[TagOrTags] = tuple()
) -> dataclasses.Field:  # pylint: disable=g-bare-generic
  """Dataclass field specification for a Fiddle-configurable dataclass field.

  This can be used to specify that a dataclass should have a default value of
  `field_type`; and that when Fiddle builds a `fdl.Buildable` for the dataclass,
  it should be initialized with `fdl.Config(field_type)`.

  Example usage:

  >>> class Parent(base_layer.BaseLayer):
  ...   child: Child = praxis_fiddle.sub_field(Child)

  Args:
    field_type: The dataclass type used by the field.
    tags: One or more tags to attach to the `fdl.Buildable`'s argument
      corresponding to the field, when building a `fdl.Buildable`.

  Returns:
    A `dataclasses.Field` specification for the field.
  """
  return fdl_field(default_factory=field_type, tags=tags,
                   configurable_factory=True)


def template_field(
    template: Callable[..., Any], tags: Optional[TagOrTags] = tuple()
) -> dataclasses.Field:  # pylint: disable=g-bare-generic
  """Dataclass field specification for a Fiddle-configurable template field.

  This can be used to specify that a dataclass should have a default value of
  `fdl.Config(template)`; and that when Fiddle builds the dataclass,
  this field should *not* be built, but should be left as a `fdl.Config`.

  Example usage:

  >>> class Parent(base_layer.BaseLayer):
  ...   child_tpl: fdl.Config[Child] = praxis_fiddle.template_field(Child)

  Args:
    template: The template type (or factory function).
    tags: One or more tags to attach to the `fdl.Buildable`'s argument
      corresponding to the field, when building a `fdl.Buildable`.

  Returns:
    A `dataclasses.Field` specification for the field.
  """
  factory = auto_config.auto_config(lambda: fdl.Config(template))  # pylint: disable=unnecessary-lambda
  tags = set(tags) | {DoNotBuild}
  return fdl_field(default_factory=factory, tags=tags)


# Typing overloads for pax_build
T = TypeVar('T')


@overload
def build(buildable: fdl.Partial[T]) -> Callable[..., T]:
  ...


@overload
def build(buildable: fdl.Partial) -> Callable[..., Any]:
  ...


@overload
def build(buildable: fdl.Config[T]) -> T:
  ...


@overload
def build(buildable: Any) -> Any:
  ...


def build(buildable):
  """Specialized version of `fdl.build` that respects the `DoNotBuild` tag.

  When building `buildable`, if any arguments are tagged with `DoNotBuild`,
  then return them as-is, rather than building them.  This makes it posible
  to keep templates unbuilt, so they can be used for deferred subtree building.

  Args:
    buildable: A `Buildable` instance to build, or a nested structure of
      `Buildable` objects.

  Returns:
    The built version of `buildable`.
  """

  def _build(value, state):
    if isinstance(value, fdl.Buildable):
      arguments = {}
      for key, sub_value in value.__arguments__.items():
        if DoNotBuild in value.__argument_tags__.get(key, ()):
          arguments[key] = sub_value
        else:
          arguments[key] = state.call(sub_value, daglish.Attr(key))
      try:
        return value.__build__(**arguments)
      except tagging.TaggedValueNotFilledError:
        raise
      except Exception as e:
        path_str = '<root>' + daglish.path_str(state.current_path)
        raise fdl.BuildError(value, path_str, e, (), arguments) from e
    else:
      return state.map_children(value)

  return _build(buildable, daglish.MemoizedTraversal.begin(_build, buildable))