# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

"""
Helper functions used for Freestyle style module writing
"""

# module members
from _freestyle import (
    ContextFunctions,
    getCurrentScene,
    integrate,
    )

from freestyle.types import (
    Interface0DIterator,
    )


from mathutils import Vector
from functools import lru_cache
from math import cos, sin, pi
from itertools import tee


# -- real utility functions  -- #

def rgb_to_bw(r, g, b):
    """ Method to convert rgb to a bw intensity value. """
    return 0.35 * r + 0.45 * g + 0.2 * b


def bound(lower, x, higher):
    """ Returns x bounded by a maximum and minimum value. equivalent to:
    return min(max(x, lower), higher)
    """
    # this is about 50% quicker than min(max(x, lower), higher)
    return (lower if x <= lower else higher if x >= higher else x)


def bounding_box(stroke):
    """
    Returns the maximum and minimum coordinates (the bounding box) of the stroke's vertices
    """
    x, y = zip(*(svert.point for svert in stroke))
    return (Vector((min(x), min(y))), Vector((max(x), max(y))))

# -- General helper functions -- #

@lru_cache(maxsize=32)
def phase_to_direction(length):
    """
    Returns a list of tuples each containing:
    - the phase
    - a Vector with the values of the cosine and sine of 2pi * phase  (the direction)
    """
    results = list()
    for i in range(length):
        phase = i / (length - 1)
        results.append((phase, Vector((cos(2 * pi * phase), sin(2 * pi * phase)))))
    return results


# -- helper functions for chaining -- #

def get_chain_length(ve, orientation):
    """Returns the 2d length of a given ViewEdge """
    from freestyle.chainingiterators import pyChainSilhouetteGenericIterator
    length = 0.0
    # setup iterator
    _it = pyChainSilhouetteGenericIterator(False, False)
    _it.begin = ve
    _it.current_edge = ve
    _it.orientation = orientation
    _it.init()

    # run iterator till end of chain
    while not (_it.is_end):
        length += _it.object.length_2d
        if (_it.is_begin):
            # _it has looped back to the beginning;
            # break to prevent infinite loop
            break
        _it.increment()

    # reset iterator
    _it.begin = ve
    _it.current_edge = ve
    _it.orientation = orientation

    # run iterator till begin of chain
    if not _it.is_begin:
        _it.decrement()
        while not (_it.is_end or _it.is_begin):
            length += _it.object.length_2d
            _it.decrement()

    return length

def find_matching_vertex(id, it):
    """Finds the matching vertex, or returns None """
    return next((ve for ve in it if ve.id == id), None)

# -- helper functions for iterating -- #

def pairwise(iterable):
    """Yields a tuple containing the previous and current object """
    
    # try:
    #     it = iter(iterable)
    #     a = it.__class__(it)
    #     b = it.__class__(it)
    # except TypeError:
    #     a,b = tee(iterable)
    a,b = tee(iterable)
    next(b, None)
    return zip(a, b)

def tripplewise(iterable):
    """Yields a tuple containing the current object and its immediate neighbors """
    a, b, c = tee(iterable)
    next(b, None)
    next(c, None)
    next(c, None)
    return zip(a, b, c)


def iter_t2d_along_stroke(stroke):
    """ Yields the progress along the stroke """
    total = stroke.length_2d
    distance = 0.0
    # yield for the comparison from the first vertex to itself
    yield 0.0
    for prev, svert in pairwise(stroke):
        distance += (prev.point - svert.point).length
        yield min(distance / total, 1.0) if total != 0.0 else 0.0


def iter_distance_from_camera(stroke, range_min, range_max):
    """
    Yields the distance to the camera relative to the maximum
    possible distance for every stroke vertex, constrained by
    given minimum and maximum values.
    """
    normfac = range_max - range_min
    for svert in stroke:
        # length in the camera coordinate
        distance = svert.point_3d.length
        if range_min < distance < range_max:
            yield (distance - range_min) / normfac
        else:
            yield 0.0 if range_min > distance else 1.0


def iter_distance_from_object(stroke, location, range_min, range_max):
    """
    yields the distance to the given object relative to the maximum
    possible distance for every stroke vertex, constrained by
    given minimum and maximum values.
    """
    normfac = range_max - range_min  # normalization factor
    for svert in stroke:
        distance = (svert.point_3d - location).length # in the camera coordinate
        if range_min < distance < range_max:
            yield (distance - range_min) / normfac
        else:
            yield 0.0 if distance < range_min else 1.0


def get_material_value(material, attribute):
    """
    Returns a specific material attribute
    from the vertex' underlying material.
    """
    # main
    if attribute == 'DIFF':
        return rgb_to_bw(*material.diffuse[0:3])
    elif attribute == 'ALPHA':
        return material.diffuse[3]
    elif attribute == 'SPEC':
        return rgb_to_bw(*material.specular[0:3])
    # diffuse seperate
    elif attribute == 'DIFF_R':
        return material.diffuse[0]
    elif attribute == 'DIFF_G':
        return material.diffuse[1]
    elif attribute == 'DIFF_B':
        return material.diffuse[2]
    # specular seperate
    elif attribute == 'SPEC_R':
        return material.specular[0]
    elif attribute == 'SPEC_G':
        return material.specular[1]
    elif attribute == 'SPEC_B':
        return material.specular[2]
    elif attribute == 'SPEC_HARDNESS':
        return material.shininess
    else:
        raise ValueError("unexpected material attribute: " + attribute)


def iter_distance_along_stroke(stroke):
    """
    yields the absolute distance between
    the current and preceding vertex.
    """
    distance = 0.0
    # the positions need to be copied, because they are changed in the calling function
    points = tuple(svert.point.copy() for svert in stroke)
    yield distance
    for prev, curr in pairwise(points):
        distance += (prev - curr).length
        yield distance

# -- mathmatical operations -- #

def stroke_curvature(it):
    """
    Compute the 2D curvature at the stroke vertex pointed by the iterator 'it'.
    K = 1 / R
    where R is the radius of the circle going through the current vertex and its neighbors
    """

    if it.is_end or it.is_begin:
        return 0.0

    next = it.incremented().point
    prev = it.decremented().point
    current = it.object.point


    ab = (current - prev)
    bc = (next - current)
    ac = (prev - next)

    a, b, c = ab.length, bc.length, ac.length

    try:
        area = 0.5 * ab.cross(ac)
        K = (4 * area) / (a * b * c)
        K = bound(0.0, K, 1.0)

    except ZeroDivisionError:
        K = 0.0

    return K


def stroke_normal(stroke):
    """
    Compute the 2D normal at the stroke vertex pointed by the iterator
    'it'.  It is noted that Normal2DF0D computes normals based on
    underlying FEdges instead, which is inappropriate for strokes when
    they have already been modified by stroke geometry modifiers.
    """
    n = len(stroke) - 1

    for i, svert in enumerate(stroke):
        if i == 0:
            e = stroke[i + 1].point - svert.point
            yield Vector((e[1], -e[0])).normalized()
        elif i == n:
            e = svert.point - stroke[i - 1].point
            yield Vector((e[1], -e[0])).normalized()
        else:
            e1 = stroke[i + 1].point - svert.point
            e2 = svert.point - stroke[i - 1].point
            n1 = Vector((e1[1], -e1[0])).normalized()
            n2 = Vector((e2[1], -e2[0])).normalized()
            yield (n1 + n2).normalized()


# DEPRECACTED and unused, the version above is way quicker
def stroke_normal1(it):
    """
    Compute the 2D normal at the stroke vertex pointed by the iterator
    'it'.  It is noted that Normal2DF0D computes normals based on
    underlying FEdges instead, which is inappropriate for strokes when
    they have already been modified by stroke geometry modifiers.
    """
    # first stroke segment
    #it_next = it.incremented()
    it_next = Interface0DIterator(it)
    it_next.increment()
    if it.is_begin:
        e = it_next.object.point_2d - it.object.point_2d
        return Vector((e[1], -e[0])).normalized()
    # last stroke segment
    #it_prev = it.decremented()
    it_prev = Interface0DIterator(it)
    it_prev.decrement()
    if it_next.is_end:
        e = it.object.point_2d - it_prev.object.point_2d
        return Vector((e[1], -e[0])).normalized()
    # two subsequent stroke segments
    e1 = it_next.object.point_2d - it.object.point_2d
    e2 = it.object.point_2d - it_prev.object.point_2d
    n1 = Vector((e1[1], -e1[0])).normalized()
    n2 = Vector((e2[1], -e2[0])).normalized()
    return (n1 + n2).normalized()