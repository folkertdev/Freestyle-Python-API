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

#  Filename : parameter_editor.py
#  Authors  : Tamito Kajiyama
#  Date     : 26/07/2010
#  Purpose  : Interactive manipulation of stylization parameters

from freestyle.types import (
    BinaryPredicate1D,
    IntegrationType,
    Interface0DIterator,
    Nature,
    Noise,
    Operators,
    StrokeAttribute,
    UnaryPredicate0D,
    UnaryPredicate1D,
    TVertex,
    Material,
    ViewEdge,
    )
from freestyle.chainingiterators import (
    ChainPredicateIterator,
    ChainSilhouetteIterator,
    pySketchyChainSilhouetteIterator,
    pySketchyChainingIterator,
    )
from freestyle.functions import (
    Curvature2DAngleF0D,
    Normal2DF0D,
    QuantitativeInvisibilityF1D,
    VertexOrientation2DF0D,
    CurveMaterialF0D,
    )
from freestyle.predicates import (
    AndUP1D,
    ContourUP1D,
    ExternalContourUP1D,
    FalseBP1D,
    FalseUP1D,
    Length2DBP1D,
    NotBP1D,
    NotUP1D,
    OrUP1D,
    QuantitativeInvisibilityUP1D,
    TrueBP1D,
    TrueUP1D,
    WithinImageBoundaryUP1D,
    pyNatureUP1D,
    pyZBP1D,
    )
from freestyle.shaders import (
    BackboneStretcherShader,
    BezierCurveShader,
    BlenderTextureShader,
    ConstantColorShader,
    GuidingLinesShader,
    PolygonalizationShader,
    SamplingShader,
    SpatialNoiseShader,
    StrokeShader,
    StrokeTextureStepShader,
    TipRemoverShader,
    pyBluePrintCirclesShader,
    pyBluePrintEllipsesShader,
    pyBluePrintSquaresShader,
    #RoundCapShader,
    #SquareCapShader,
    )
from freestyle.utils import (
    ContextFunctions,
    getCurrentScene,
    stroke_normal,
    bound,
    pairwise,
    iter_distance_along_stroke,
    get_material_value,
    iter_t2d_along_stroke,
    iter_distance_from_camera,
    iter_distance_from_object
    )
from _freestyle import (
    blendRamp,
    evaluateColorRamp,
    evaluateCurveMappingF,
    )

import time

from mathutils import Vector
from math import pi, sin, cos, acos, radians
from itertools import cycle, tee


class ColorRampModifier(StrokeShader):
    def __init__(self, blend, influence, ramp):
        StrokeShader.__init__(self)
        self.__blend = blend
        self.__influence = influence
        self.__ramp = ramp

    def evaluate(self, t):
        col = evaluateColorRamp(self.__ramp, t)
        return col.xyz  # omit alpha

    def blend_ramp(self, a, b):
        return blendRamp(self.__blend, a, self.__influence, b)


class ScalarBlendModifier(StrokeShader):
    def __init__(self, blend, influence):
        StrokeShader.__init__(self)
        self.__blend = blend
        self.__influence = influence

    def blend(self, v1, v2):
        fac = self.__influence
        facm = 1.0 - fac
        if self.__blend == 'MIX':
            v1 = facm * v1 + fac * v2
        elif self.__blend == 'ADD':
            v1 += fac * v2
        elif self.__blend == 'MULTIPLY':
            v1 *= facm + fac * v2
        elif self.__blend == 'SUBTRACT':
            v1 -= fac * v2
        elif self.__blend == 'DIVIDE':
            v1 = facm * v1 + fac * v1 / v2 if v2 != 0.0 else v1
        elif self.__blend == 'DIFFERENCE':
            v1 = facm * v1 + fac * abs(v1 - v2)
        elif self.__blend == 'MININUM':
            v1 = min(fac * v2, v1)
        elif self.__blend == 'MAXIMUM':
            v1 = max(fac * v2, v1)
        else:
            raise ValueError("unknown curve blend type: " + self.__blend)
        return v1


class CurveMappingModifier(ScalarBlendModifier):
    def __init__(self, blend, influence, mapping, invert, curve):
        ScalarBlendModifier.__init__(self, blend, influence)
        assert mapping in {'LINEAR', 'CURVE'}
        self.__mapping = getattr(self, mapping)
        self.__invert = invert
        self.__curve = curve

    def LINEAR(self, t):
        return (1.0 - t) if self.__invert else t

    def CURVE(self, t):
        return evaluateCurveMappingF(self.__curve, 0, t)

    def evaluate(self, t):
        return self.__mapping(t)


class ThicknessModifierMixIn:
    def __init__(self):
        scene = getCurrentScene()
        self.__persp_camera = (scene.camera.data.type == 'PERSP')

    def set_thickness(self, sv, outer, inner):
        fe = sv.first_svertex.get_fedge(sv.second_svertex)
        nature = fe.nature
        if (nature & Nature.BORDER):
            if self.__persp_camera:
                point = -sv.point_3d.normalized()
                dir = point.dot(fe.normal_left)
            else:
                dir = fe.normal_left.z
            if dir < 0.0:  # the back side is visible
                outer, inner = inner, outer
        elif (nature & Nature.SILHOUETTE):
            if fe.is_smooth:  # TODO more tests needed
                outer, inner = inner, outer
        else:
            outer = inner = (outer + inner) / 2
        sv.attribute.thickness = (outer, inner)


class ThicknessBlenderMixIn(ThicknessModifierMixIn):
    def __init__(self, position, ratio):
        ThicknessModifierMixIn.__init__(self)
        self.__position = position
        self.__ratio = ratio

    def blend_thickness(self, outer, inner, v):
        v = self.blend(outer + inner, v)
        if self.__position == 'CENTER':
            outer = v * 0.5
            inner = v - outer
        elif self.__position == 'INSIDE':
            outer = 0
            inner = v
        elif self.__position == 'OUTSIDE':
            outer = v
            inner = 0
        elif self.__position == 'RELATIVE':
            outer = v * self.__ratio
            inner = v - outer
        else:
            raise ValueError("unknown thickness position: " + self.__position)
        return outer, inner


class BaseColorShader(ConstantColorShader):
    pass


class BaseThicknessShader(StrokeShader, ThicknessModifierMixIn):
    def __init__(self, thickness, position, ratio):
        StrokeShader.__init__(self)
        ThicknessModifierMixIn.__init__(self)
        if position == 'CENTER':
            self.__outer = thickness * 0.5
            self.__inner = thickness - self.__outer
        elif position == 'INSIDE':
            self.__outer = 0
            self.__inner = thickness
        elif position == 'OUTSIDE':
            self.__outer = thickness
            self.__inner = 0
        elif position == 'RELATIVE':
            self.__outer = thickness * ratio
            self.__inner = thickness - self.__outer
        else:
            raise ValueError("unknown thickness position: " + position)

    def shade(self, stroke):
        for svert in stroke:
            self.set_thickness(svert, self.__outer, self.__inner)


# Along Stroke modifiers

class ColorAlongStrokeShader(ColorRampModifier):
    """Maps a ramp to the color of the stroke, using the curvilinear abscissa (t) """
    def shade(self, stroke):
        for svert, t in zip(stroke, iter_t2d_along_stroke(stroke)):
            a = svert.attribute.color
            b = self.evaluate(t)
            svert.attribute.color = self.blend_ramp(a, b)


class AlphaAlongStrokeShader(CurveMappingModifier):
    """Maps a curve to the alpha/transparancy of the stroke, using the curvilinear abscissa (t) """
    def shade(self, stroke):
        for svert, t in zip(stroke, iter_t2d_along_stroke(stroke)):
            a = svert.attribute.alpha
            b = self.evaluate(t)
            svert.attribute.alpha = self.blend(a, b)


class ThicknessAlongStrokeShader(ThicknessBlenderMixIn, CurveMappingModifier):
    """Maps a curve to the thickness of the stroke, using the curvilinear abscissa (t) """
    def __init__(self, thickness_position, thickness_ratio,
                 blend, influence, mapping, invert, curve, value_min, value_max):
        ThicknessBlenderMixIn.__init__(self, thickness_position, thickness_ratio)
        CurveMappingModifier.__init__(self, blend, influence, mapping, invert, curve)
        self.__value_min = value_min
        self.__value_max = value_max

    def shade(self, stroke):
        delta = self.__value_max - self.__value_min
        for svert, t in zip(stroke, iter_t2d_along_stroke(stroke)):
            (R, L) = svert.attribute.thickness
            b = self.__value_min + self.evaluate(t) * delta
            (R, L) = self.blend_thickness(R, L, b)
            self.set_thickness(svert, R, L)


# -- Distance from Camera modifiers -- #

class ColorDistanceFromCameraShader(ColorRampModifier):
    """Picks a color value from a ramp based on the vertex' distance from the camera """
    def __init__(self, blend, influence, ramp, range_min, range_max):
        ColorRampModifier.__init__(self, blend, influence, ramp)
        self.__range_min = range_min
        self.__range_max = range_max

    def shade(self, stroke):
        it = iter_distance_from_camera(stroke, self.__range_min, self.__range_max)
        for svert, t in zip(stroke, it):
            a = svert.attribute.color
            b = self.evaluate(t)
            svert.attribute.color = self.blend_ramp(a, b)


class AlphaDistanceFromCameraShader(CurveMappingModifier):
    """Picks an alpha value from a curve based on the vertex' distance from the camera """
    def __init__(self, blend, influence, mapping, invert, curve, range_min, range_max):
        CurveMappingModifier.__init__(self, blend, influence, mapping, invert, curve)
        self.__range_min = range_min
        self.__range_max = range_max

    def shade(self, stroke):
        it = iter_distance_from_camera(stroke, self.__range_min, self.__range_max)
        for svert, t in zip(stroke, it):
            a = svert.attribute.alpha
            b = self.evaluate(t)
            svert.attribute.alpha = self.blend(a, b)


class ThicknessDistanceFromCameraShader(ThicknessBlenderMixIn, CurveMappingModifier):
    """Picks a thickness value from a curve based on the vertex' distance from the camera """
    def __init__(self, thickness_position, thickness_ratio,
                 blend, influence, mapping, invert, curve, range_min, range_max, value_min, value_max):
        ThicknessBlenderMixIn.__init__(self, thickness_position, thickness_ratio)
        CurveMappingModifier.__init__(self, blend, influence, mapping, invert, curve)
        self.__range_min = range_min
        self.__range_max = range_max
        self.__value_min = value_min
        self.__value_max = value_max

    def shade(self, stroke):
        delta = self.__value_max - self.__value_min
        it = iter_distance_from_camera(stroke, self.__range_min, self.__range_max)
        for svert, t in zip(stroke, it):
            (R, L) = svert.attribute.thickness
            b = self.__value_min + self.evaluate(t) * delta
            (R, L)  = self.blend_thickness(R, L, b)
            self.set_thickness(svert, R, L)


# Distance from Object modifiers

class ColorDistanceFromObjectShader(ColorRampModifier):
    """Picks a color value from a ramp based on the vertex' distance from a given object """
    def __init__(self, blend, influence, ramp, target, range_min, range_max):
        ColorRampModifier.__init__(self, blend, influence, ramp)
        if target is None:
            raise ValueError("ColorDistanceFromObjectShader: target can't be None ")
        self.range_min = range_min
        self.range_max = range_max
        # construct a model-view matrix
        matrix = getCurrentScene().camera.matrix_world.inverted()
        # get the object location in the camera coordinate
        self.loc = matrix * target.location

    def shade(self, stroke):
        it = iter_distance_from_object(stroke, self.loc, self.range_min, self.range_max)
        for svert, t in zip(stroke, it):
            a = svert.attribute.color
            b = self.evaluate(t)
            svert.attribute.color = self.blend_ramp(a, b)


class AlphaDistanceFromObjectShader(CurveMappingModifier):
    """Picks an alpha value from a curve based on the vertex' distance from a given object """
    def __init__(self, blend, influence, mapping, invert, curve, target, range_min, range_max):
        CurveMappingModifier.__init__(self, blend, influence, mapping, invert, curve)
        if target is None:
            raise ValueError("AlphaDistanceFromObjectShader: target can't be None ")
        self.range_min = range_min
        self.range_max = range_max
        # construct a model-view matrix
        matrix = getCurrentScene().camera.matrix_world.inverted()
        # get the object location in the camera coordinate
        self.loc = matrix * target.location

    def shade(self, stroke):
        it = iter_distance_from_object(stroke, self.loc, self.range_min, self.range_max)
        for svert, t in zip(stroke, it):
            a = svert.attribute.alpha
            b = self.evaluate(t)
            svert.attribute.alpha = self.blend(a, b)


class ThicknessDistanceFromObjectShader(ThicknessBlenderMixIn, CurveMappingModifier):
    """Picks a thickness value from a curve based on the vertex' distance from a given object """
    def __init__(self, thickness_position, thickness_ratio,
                 blend, influence, mapping, invert, curve, target, range_min, range_max, value_min, value_max):
        ThicknessBlenderMixIn.__init__(self, thickness_position, thickness_ratio)
        CurveMappingModifier.__init__(self, blend, influence, mapping, invert, curve)
        if target is None:
            raise ValueError("ThicknessDistanceFromObjectShader: target can't be None ")
        self.__range_min = range_min
        self.__range_max = range_max
        self.__value_min = value_min
        self.__value_max = value_max
        # construct a model-view matrix
        matrix = getCurrentScene().camera.matrix_world.inverted()
        # get the object location in the camera coordinate
        self.loc = matrix * target.location

    def shade(self, stroke):
        it = iter_distance_from_object(stroke, self.loc, self.__range_min, self.__range_max)
        for svert, t in zip(stroke, it):
            (R, L) = svert.attribute.thickness
            b = self.__value_min + self.evaluate(t) * (self.__value_max - self.__value_min)
            (R, L) = self.blend_thickness(R, L, b)
            self.set_thickness(svert, R, L)


# Material modifiers

class ColorMaterialShader(ColorRampModifier):
    """ Assigns a color to the vertices based on their underlying material """
    def __init__(self, blend, influence, ramp, material_attribute, use_ramp):
        ColorRampModifier.__init__(self, blend, influence, ramp)
        self.attribute = material_attribute
        self.use_ramp = use_ramp
        self.func = CurveMaterialF0D()

    def shade(self, stroke):
        it = Interface0DIterator(stroke)
        if self.attribute in {'DIFF', 'SPEC'} and not self.use_ramp:
            for svert in it:
                material = self.func(it)
                a = svert.attribute.color
                b = material.diffuse[0:3] if self.attribute == 'DIFF' else material.specular[0:3]
                svert.attribute.color = self.blend_ramp(a, b)
        else:
            for svert in it:
                t = get_material_value(self.func(it), self.attribute)
                a = svert.attribute.color
                b = self.evaluate(t)
                svert.attribute.color = self.blend_ramp(a, b)


class AlphaMaterialShader(CurveMappingModifier):
    """ Assigns an alpha value to the vertices based on their underlying material """
    def __init__(self, blend, influence, mapping, invert, curve, material_attribute):
        CurveMappingModifier.__init__(self, blend, influence, mapping, invert, curve)
        self.attribute = material_attribute
        self.func = CurveMaterialF0D()

    def shade(self, stroke):
        it = Interface0DIterator(stroke)
        for svert in it:
            t = get_material_value(self.func(it), self.attribute)
            a = svert.attribute.alpha
            b = self.evaluate(t)
            svert.attribute.alpha = self.blend(a, b)


class ThicknessMaterialShader(ThicknessBlenderMixIn, CurveMappingModifier):
    """ Assigns a thickness value to the vertices based on their underlying material """
    def __init__(self, thickness_position, thickness_ratio,
                 blend, influence, mapping, invert, curve, material_attribute, value_min, value_max):
        ThicknessBlenderMixIn.__init__(self, thickness_position, thickness_ratio)
        CurveMappingModifier.__init__(self, blend, influence, mapping, invert, curve)
        self.attribute = material_attribute
        self.__value_min = value_min
        self.__value_max = value_max
        self.func = CurveMaterialF0D()

    def shade(self, stroke):
        delta = self.__value_max - self.__value_min
        it = Interface0DIterator(stroke)
        for svert in it:
            t = get_material_value(self.func(it), self.attribute)
            (R, L) = svert.attribute.thickness
            b = self.__value_min + self.evaluate(t) * delta
            (R, L) = self.blend_thickness(R, L, b)
            self.set_thickness(svert, R, L)


# Calligraphic thickness modifier

class CalligraphicThicknessShader(ThicknessBlenderMixIn, ScalarBlendModifier):
    """Thickness modifier for achieving a calligraphy-like effect """
    def __init__(self, thickness_position, thickness_ratio,
                 blend, influence, orientation, thickness_min, thickness_max):
        ThicknessBlenderMixIn.__init__(self, thickness_position, thickness_ratio)
        ScalarBlendModifier.__init__(self, blend, influence)
        self.__orientation = Vector((cos(orientation), sin(orientation)))
        self.__thickness_min = thickness_min
        self.__thickness_max = thickness_max
        self.__func = VertexOrientation2DF0D()

    def shade(self, stroke):
        delta_thickness = self.__thickness_max - self.__thickness_min
        it = Interface0DIterator(stroke)
        for svert in it:
            dir = self.__func(it)
            l = dir.length
            # make the direction orthagonal and normalize (this is the fastest way)
            dir.x, dir.y = -dir.y / l, dir.x / l
            fac = abs(dir * self.__orientation)
            b = max(0.0, self.__thickness_min + fac * delta_thickness)
            (R, L) = svert.attribute.thickness
            (R, L) = self.blend_thickness(R, L, b)
            self.set_thickness(svert, R, L)



# Geometry modifiers

class SinusDisplacementShader(StrokeShader):
    """Displaces the stroke in a sinewave-like shape """
    def __init__(self, wavelength, amplitude, phase):
        StrokeShader.__init__(self)
        self._wavelength = wavelength
        self._amplitude = amplitude
        self._phase = phase / wavelength * 2 * pi

    def shade(self, stroke):
        # to get reliable results, the normals have to be stored (need to investigate why)
        normals = tuple(stroke_normal(stroke))
        distances = iter_distance_along_stroke(stroke)
        for svert, distance, normal in zip(stroke, distances, normals):
            n = normal * self._amplitude * cos(distance / self._wavelength * 2 * pi + self._phase)
            svert.point += n
        stroke.update_length()


class PerlinNoise1DShader(StrokeShader):
    """
    Displaces the stroke using the curvilinear abscissa.  This means
    that lines with the same length and sampling interval will be
    identically distorded
    """
    def __init__(self, freq=10, amp=10, oct=4, angle=radians(45), seed=-1):
        StrokeShader.__init__(self)
        self.__noise = Noise(seed)
        self.__freq = freq
        self.__amp = amp
        self.__oct = oct
        self.__dir = Vector((cos(angle), sin(angle)))

    def shade(self, stroke):
        length = stroke.length_2d
        for svert in stroke:
            nres = self.__noise.turbulence1(length * svert.u, self.__freq, self.__amp, self.__oct)
            svert.point += nres * self.__dir
        stroke.update_length()


class PerlinNoise2DShader(StrokeShader):
    """
    Displaces the stroke using the strokes coordinates.  This means
    that in a scene no strokes will be distorded identically

    More information on the noise shaders can be found at
    freestyleintegration.wordpress.com/2011/09/25/development-updates-on-september-25/
    """
    def __init__(self, freq=10, amp=10, oct=4, angle=radians(45), seed=-1):
        StrokeShader.__init__(self)
        self.__noise = Noise(seed)
        self.__freq = freq
        self.__amp = amp
        self.__oct = oct
        self.__dir = Vector((cos(angle), sin(angle)))

    def shade(self, stroke):
        for svert in stroke:
            projected = Vector((svert.projected_x, svert.projected_y))
            nres = self.__noise.turbulence2(projected, self.__freq, self.__amp, self.__oct)
            svert.point += nres * self.__dir
        stroke.update_length()


class Offset2DShader(StrokeShader):
    """Offsets the stroke by a given amount """
    def __init__(self, start, end, x, y):
        StrokeShader.__init__(self)
        self.__start = start
        self.__end = end
        self.__xy = Vector((x, y))

    def shade(self, stroke):
        for svert, n in zip(stroke, tuple(stroke_normal(stroke))):
            a = self.__start + svert.u * (self.__end - self.__start)
            svert.point += (n * a) + self.__xy
        stroke.update_length()


class Transform2DShader(StrokeShader):
    """Transforms the stroke (scale, rotation, location) around a given pivot point """
    def __init__(self, pivot, scale_x, scale_y, angle, pivot_u, pivot_x, pivot_y):
        StrokeShader.__init__(self)
        self.__pivot = pivot
        self.scale = Vector((scale_x, scale_y))
        self.cos_theta = cos(angle)
        self.sin_theta = sin(angle)
        self.__pivot_u = pivot_u
        self.__pivot_x = pivot_x
        self.__pivot_y = pivot_y
        if not pivot in {'START', 'END', 'CENTER', 'ABSOLUTE', 'PARAM'}:
            raise ValueError("expected pivot in {'START', 'END', 'CENTER', 'ABSOLUTE', 'PARAM'}, not" + pivot)

    def shade(self, stroke):
        # determine the pivot of scaling and rotation operations
        if self.__pivot == 'START':
            pivot = stroke[0].point
        elif self.__pivot == 'END':
            pivot = stroke[-1].point
        elif self.__pivot == 'CENTER':
            pivot = (1 / len(stroke)) * sum((svert.point for svert in stroke), Vector((0.0, 0.0)))
        elif self.__pivot == 'ABSOLUTE':
            pivot = Vector((self.__pivot_x, self.__pivot_y))
        elif self.__pivot == 'PARAM':
            if self.__pivot_u < stroke[0].u:
                pivot = stroke[0].point
            else:
                for prev, svert in pairwise(stroke):
                    if self.__pivot_u < svert.u:
                        break
                pivot = svert.point + (svert.u - self.__pivot_u) * (prev.point - svert.point)


        # apply scaling and rotation operations
        for svert in stroke:
            p = (svert.point - pivot)
            x = p.x * self.scale.x
            y = p.y * self.scale.y
            p.x = x * self.cos_theta - y * self.sin_theta
            p.y = x * self.sin_theta + y * self.cos_theta
            svert.point = p + pivot
        stroke.update_length()


# Predicates and helper functions

class QuantitativeInvisibilityRangeUP1D(UnaryPredicate1D):
    def __init__(self, qi_start, qi_end):
        UnaryPredicate1D.__init__(self)
        self.__getQI = QuantitativeInvisibilityF1D()
        self.__qi_start = qi_start
        self.__qi_end = qi_end

    def __call__(self, inter):
        qi = self.__getQI(inter)
        return self.__qi_start <= qi <= self.__qi_end


class ObjectNamesUP1D(UnaryPredicate1D):
    def __init__(self, names, negative):
        UnaryPredicate1D.__init__(self)
        self._names = names
        self._negative = negative

    def __call__(self, viewEdge):
        found = viewEdge.viewshape.name in self._names
        if self._negative:
            return not found
        return found


# -- Split by dashed line pattern -- #

class SplitPatternStartingUP0D(UnaryPredicate0D):
    def __init__(self, controller):
        UnaryPredicate0D.__init__(self)
        self._controller = controller

    def __call__(self, inter):
        return self._controller.start()


class SplitPatternStoppingUP0D(UnaryPredicate0D):
    def __init__(self, controller):
        UnaryPredicate0D.__init__(self)
        self._controller = controller

    def __call__(self, inter):
        return self._controller.stop()


class SplitPatternController:
    def __init__(self, pattern, sampling):
        self.sampling = float(sampling)
        k = len(pattern) // 2
        n = k * 2
        #self.start_pos = [pattern[i] + pattern[i + 1] for i in range(0, n, 2)]
        #self.stop_pos = [pattern[i] for i in range(0, n, 2)]
        self.start_pos = [prev + current for prev, current in pairwise(pattern)]
        self.stop_pos = [prev for prev, _ in pairwise(pattern)]
        self.init()

    def init(self):
        self.start_len = 0.0
        self.start_idx = 0
        self.stop_len = self.sampling
        self.stop_idx = 0

    def start(self):
        self.start_len += self.sampling
        if abs(self.start_len - self.start_pos[self.start_idx]) < self.sampling / 2.0:
            self.start_len = 0.0
            self.start_idx = (self.start_idx + 1) % len(self.start_pos)
            return True
        return False

    def stop(self):
        if self.start_len > 0.0:
            self.init()
        self.stop_len += self.sampling
        if abs(self.stop_len - self.stop_pos[self.stop_idx]) < self.sampling / 2.0:
            self.stop_len = self.sampling
            self.stop_idx = (self.stop_idx + 1) % len(self.stop_pos)
            return True
        return False


# Dashed line

class DashedLineShader(StrokeShader):
    def __init__(self, pattern):
        StrokeShader.__init__(self)
        self._pattern = pattern

    def shade(self, stroke):
        start = 0.0  # 2D curvilinear length
        visible = True
        """ The extra 'sampling' term is added below, because the
        visibility attribute of the i-th vertex refers to the
        visibility of the stroke segment between the i-th and
        (i+1)-th vertices. """
        sampling = 1.0
        it = stroke.stroke_vertices_begin(sampling)
        for svert, pattern in zip(it, cycle(self._pattern)):

            pos = it.t  # curvilinear abscissa

            if pos - start + sampling > pattern:
                start = pos
                visible = not visible

            if not visible:
                it.object.attribute.visible = False



# predicates for chaining

class AngleLargerThanBP1D(BinaryPredicate1D):
    def __init__(self, angle):
        BinaryPredicate1D.__init__(self)
        self._angle = angle

    def __call__(self, i1, i2):
        sv1a = i1.first_fedge.first_svertex.point_2d
        sv1b = i1.last_fedge.second_svertex.point_2d
        sv2a = i2.first_fedge.first_svertex.point_2d
        sv2b = i2.last_fedge.second_svertex.point_2d
        if (sv1a - sv2a).length < 1e-6:
            dir1 = sv1a - sv1b
            dir2 = sv2b - sv2a
        elif (sv1b - sv2b).length < 1e-6:
            dir1 = sv1b - sv1a
            dir2 = sv2a - sv2b
        elif (sv1a - sv2b).length < 1e-6:
            dir1 = sv1a - sv1b
            dir2 = sv2a - sv2b
        elif (sv1b - sv2a).length < 1e-6:
            dir1 = sv1b - sv1a
            dir2 = sv2b - sv2a
        else:
            return False
        denom = dir1.length * dir2.length
        if denom < 1e-6:
            return False
        x = (dir1 * dir2) / denom
        return acos(bound(-1.0, x, 1.0)) > self._angle

# predicates for selection

class LengthThresholdUP1D(UnaryPredicate1D):
    def __init__(self, length_min=None, length_max=None):
        UnaryPredicate1D.__init__(self)
        self._length_min = length_min
        self._length_max = length_max

    def __call__(self, inter):
        length = inter.length_2d
        if self._length_min is not None and length < self._length_min:
            return False
        if self._length_max is not None and length > self._length_max:
            return False
        return True

class FaceMarkBothUP1D(UnaryPredicate1D):
    def __call__(self, inter:ViewEdge):
        while fe is not None:
            if fe.is_smooth:
                if fe.face_mark:
                    return True
            elif (fe.nature & Nature.BORDER):
                if fe.face_mark_left:
                    return True
            else:
                if fe.face_mark_right and fe.face_mark_left:
                    return True
            fe = fe.next_fedge
        return False


class FaceMarkOneUP1D(UnaryPredicate1D):
    def __call__(self, inter:ViewEdge):
        fe = inter.first_fedge
        while fe is not None:
            if fe.is_smooth:
                if fe.face_mark:
                    return True
            elif (fe.nature & Nature.BORDER):
                if fe.face_mark_left:
                    return True
            else:
                if fe.face_mark_right or fe.face_mark_left:
                    return True
            fe = fe.next_fedge
        return False


# predicates for splitting

class MaterialBoundaryUP0D(UnaryPredicate0D):
    def __call__(self, it):
        try:
            it.decrement()
            prev = it.object
            svert = next(it)
            succ = next(it)
        except (RuntimeError, StopIteration) as e:
            # iterator at start or begin
            return False
        
        fe = svert.get_fedge(prev)
        idx1 = fe.material_index if fe.is_smooth else fe.material_index_left
        fe = svert.get_fedge(succ)
        idx2 = fe.material_index if fe.is_smooth else fe.material_index_left
        return idx1 != idx2

class Curvature2DAngleThresholdUP0D(UnaryPredicate0D):
    def __init__(self, angle_min=None, angle_max=None):
        UnaryPredicate0D.__init__(self)
        self._angle_min = angle_min
        self._angle_max = angle_max
        self._func = Curvature2DAngleF0D()

    def __call__(self, inter):
        angle = pi - self._func(inter)
        if self._angle_min is not None and angle < self._angle_min:
            return True
        if self._angle_max is not None and angle > self._angle_max:
            return True
        return False


class Length2DThresholdUP0D(UnaryPredicate0D):
    def __init__(self, length_limit):
        UnaryPredicate0D.__init__(self)
        self._length_limit = length_limit
        self._t = 0.0

    def __call__(self, inter):
        t = inter.t  # curvilinear abscissa
        if t < self._t:
            self._t = 0.0
            return False
        if t - self._t < self._length_limit:
            return False
        self._t = t
        return True


# Seed for random number generation

class Seed:
    def __init__(self):
        self.t_max = 2 ** 15
        self.t = int(time.time()) % self.t_max

    def get(self, seed):
        if seed < 0:
            self.t = (self.t + 1) % self.t_max
            return self.t
        return seed

_seed = Seed()


integration_types = {
    'MEAN': IntegrationType.MEAN,
    'MIN': IntegrationType.MIN,
    'MAX': IntegrationType.MAX,
    'FIRST': IntegrationType.FIRST,
    'LAST': IntegrationType.LAST}


# main function for parameter processing

def process(layer_name, lineset_name):
    scene = getCurrentScene()
    layer = scene.render.layers[layer_name]
    lineset = layer.freestyle_settings.linesets[lineset_name]
    linestyle = lineset.linestyle

    selection_criteria = []
    # prepare selection criteria by visibility
    if lineset.select_by_visibility:
        if lineset.visibility == 'VISIBLE':
            selection_criteria.append(
                QuantitativeInvisibilityUP1D(0))
        elif lineset.visibility == 'HIDDEN':
            selection_criteria.append(
                NotUP1D(QuantitativeInvisibilityUP1D(0)))
        elif lineset.visibility == 'RANGE':
            selection_criteria.append(
                QuantitativeInvisibilityRangeUP1D(lineset.qi_start, lineset.qi_end))
    # prepare selection criteria by edge types
    if lineset.select_by_edge_types:
        edge_type_criteria = []
        if lineset.select_silhouette:
            upred = pyNatureUP1D(Nature.SILHOUETTE)
            edge_type_criteria.append(NotUP1D(upred) if lineset.exclude_silhouette else upred)
        if lineset.select_border:
            upred = pyNatureUP1D(Nature.BORDER)
            edge_type_criteria.append(NotUP1D(upred) if lineset.exclude_border else upred)
        if lineset.select_crease:
            upred = pyNatureUP1D(Nature.CREASE)
            edge_type_criteria.append(NotUP1D(upred) if lineset.exclude_crease else upred)
        if lineset.select_ridge_valley:
            upred = pyNatureUP1D(Nature.RIDGE)
            edge_type_criteria.append(NotUP1D(upred) if lineset.exclude_ridge_valley else upred)
        if lineset.select_suggestive_contour:
            upred = pyNatureUP1D(Nature.SUGGESTIVE_CONTOUR)
            edge_type_criteria.append(NotUP1D(upred) if lineset.exclude_suggestive_contour else upred)
        if lineset.select_material_boundary:
            upred = pyNatureUP1D(Nature.MATERIAL_BOUNDARY)
            edge_type_criteria.append(NotUP1D(upred) if lineset.exclude_material_boundary else upred)
        if lineset.select_edge_mark:
            upred = pyNatureUP1D(Nature.EDGE_MARK)
            edge_type_criteria.append(NotUP1D(upred) if lineset.exclude_edge_mark else upred)
        if lineset.select_contour:
            upred = ContourUP1D()
            edge_type_criteria.append(NotUP1D(upred) if lineset.exclude_contour else upred)
        if lineset.select_external_contour:
            upred = ExternalContourUP1D()
            edge_type_criteria.append(NotUP1D(upred) if lineset.exclude_external_contour else upred)
        if lineset.edge_type_combination == 'OR':
            upred = OrUP1D(*edge_type_criteria)
        else:
            upred = AndUP1D(*edge_type_criteria)
        if upred is not None:
            if lineset.edge_type_negation == 'EXCLUSIVE':
                upred = NotUP1D(upred)
            selection_criteria.append(upred)
    # prepare selection criteria by face marks
    if lineset.select_by_face_marks:
        if lineset.face_mark_condition == 'BOTH':
            upred = FaceMarkBothUP1D()
        else:
            upred = FaceMarkOneUP1D()

        if lineset.face_mark_negation == 'EXCLUSIVE':
            upred = NotUP1D(upred)
        selection_criteria.append(upred)
    # prepare selection criteria by group of objects
    if lineset.select_by_group:
        if lineset.group is not None:
            names = {ob.name: True for ob in lineset.group.objects}
            upred = ObjectNamesUP1D(names, lineset.group_negation == 'EXCLUSIVE')
            selection_criteria.append(upred)
    # prepare selection criteria by image border
    if lineset.select_by_image_border:
        upred = WithinImageBoundaryUP1D(*ContextFunctions.get_border())
        selection_criteria.append(upred)
    # select feature edges
    upred = AndUP1D(*selection_criteria)
    if upred is None:
        upred = TrueUP1D()
    Operators.select(upred)
    # join feature edges to form chains
    if linestyle.use_chaining:
        if linestyle.chaining == 'PLAIN':
            if linestyle.use_same_object:
                Operators.bidirectional_chain(ChainSilhouetteIterator(), NotUP1D(upred))
            else:
                Operators.bidirectional_chain(ChainPredicateIterator(upred, TrueBP1D()), NotUP1D(upred))
        elif linestyle.chaining == 'SKETCHY':
            if linestyle.use_same_object:
                Operators.bidirectional_chain(pySketchyChainSilhouetteIterator(linestyle.rounds))
            else:
                Operators.bidirectional_chain(pySketchyChainingIterator(linestyle.rounds))
    else:
        Operators.chain(ChainPredicateIterator(FalseUP1D(), FalseBP1D()), NotUP1D(upred))
    # split chains
    if linestyle.material_boundary:
        Operators.sequential_split(MaterialBoundaryUP0D())
    if linestyle.use_angle_min or linestyle.use_angle_max:
        angle_min = linestyle.angle_min if linestyle.use_angle_min else None
        angle_max = linestyle.angle_max if linestyle.use_angle_max else None
        Operators.sequential_split(Curvature2DAngleThresholdUP0D(angle_min, angle_max))
    if linestyle.use_split_length:
        Operators.sequential_split(Length2DThresholdUP0D(linestyle.split_length), 1.0)
    if linestyle.use_split_pattern:
        pattern = []
        if linestyle.split_dash1 > 0 and linestyle.split_gap1 > 0:
            pattern.append(linestyle.split_dash1)
            pattern.append(linestyle.split_gap1)
        if linestyle.split_dash2 > 0 and linestyle.split_gap2 > 0:
            pattern.append(linestyle.split_dash2)
            pattern.append(linestyle.split_gap2)
        if linestyle.split_dash3 > 0 and linestyle.split_gap3 > 0:
            pattern.append(linestyle.split_dash3)
            pattern.append(linestyle.split_gap3)
        if len(pattern) > 0:
            sampling = 1.0
            controller = SplitPatternController(pattern, sampling)
            Operators.sequential_split(SplitPatternStartingUP0D(controller),
                                       SplitPatternStoppingUP0D(controller),
                                       sampling)
    # select chains
    if linestyle.use_length_min or linestyle.use_length_max:
        length_min = linestyle.length_min if linestyle.use_length_min else None
        length_max = linestyle.length_max if linestyle.use_length_max else None
        Operators.select(LengthThresholdUP1D(length_min, length_max))
    # sort selected chains
    if linestyle.use_sorting:
        integration = integration_types.get(linestyle.integration_type, IntegrationType.MEAN)
        if linestyle.sort_key == 'DISTANCE_FROM_CAMERA':
            bpred = pyZBP1D(integration)
        elif linestyle.sort_key == '2D_LENGTH':
            bpred = Length2DBP1D()
        if linestyle.sort_order == 'REVERSE':
            bpred = NotBP1D(bpred)
        Operators.sort(bpred)
    # prepare a list of stroke shaders
    shaders_list = []
    for m in linestyle.geometry_modifiers:
        if not m.use:
            continue
        if m.type == 'SAMPLING':
            shaders_list.append(SamplingShader(
                m.sampling))
        elif m.type == 'BEZIER_CURVE':
            shaders_list.append(BezierCurveShader(
                m.error))
        elif m.type == 'SINUS_DISPLACEMENT':
            shaders_list.append(SinusDisplacementShader(
                m.wavelength, m.amplitude, m.phase))
        elif m.type == 'SPATIAL_NOISE':
            shaders_list.append(SpatialNoiseShader(
                m.amplitude, m.scale, m.octaves, m.smooth, m.use_pure_random))
        elif m.type == 'PERLIN_NOISE_1D':
            shaders_list.append(PerlinNoise1DShader(
                m.frequency, m.amplitude, m.octaves, m.angle, _seed.get(m.seed)))
        elif m.type == 'PERLIN_NOISE_2D':
            shaders_list.append(PerlinNoise2DShader(
                m.frequency, m.amplitude, m.octaves, m.angle, _seed.get(m.seed)))
        elif m.type == 'BACKBONE_STRETCHER':
            shaders_list.append(BackboneStretcherShader(
                m.backbone_length))
        elif m.type == 'TIP_REMOVER':
            shaders_list.append(TipRemoverShader(
                m.tip_length))
        elif m.type == 'POLYGONIZATION':
            shaders_list.append(PolygonalizationShader(
                m.error))
        elif m.type == 'GUIDING_LINES':
            shaders_list.append(GuidingLinesShader(
                m.offset))
        elif m.type == 'BLUEPRINT':
            if m.shape == 'CIRCLES':
                shaders_list.append(pyBluePrintCirclesShader(
                    m.rounds, m.random_radius, m.random_center))
            elif m.shape == 'ELLIPSES':
                shaders_list.append(pyBluePrintEllipsesShader(
                    m.rounds, m.random_radius, m.random_center))
            elif m.shape == 'SQUARES':
                shaders_list.append(pyBluePrintSquaresShader(
                    m.rounds, m.backbone_length, m.random_backbone))
        elif m.type == '2D_OFFSET':
            shaders_list.append(Offset2DShader(
                m.start, m.end, m.x, m.y))
        elif m.type == '2D_TRANSFORM':
            shaders_list.append(Transform2DShader(
                m.pivot, m.scale_x, m.scale_y, m.angle, m.pivot_u, m.pivot_x, m.pivot_y))
    if linestyle.use_texture:
        has_tex = False
        for slot in linestyle.texture_slots:
            if slot is not None:
                shaders_list.append(BlenderTextureShader(slot))
                has_tex = True
        if has_tex:
            shaders_list.append(StrokeTextureStepShader(linestyle.texture_spacing))
    color = linestyle.color
    if (not linestyle.use_chaining) or (linestyle.chaining == 'PLAIN' and linestyle.use_same_object):
        thickness_position = linestyle.thickness_position
    else:
        thickness_position = 'CENTER'
        import bpy
        if bpy.app.debug_freestyle:
            print("Warning: Thickness position options are applied when chaining is disabled\n"
                  "         or the Plain chaining is used with the Same Object option enabled.")
    shaders_list.append(BaseColorShader(color.r, color.g, color.b, linestyle.alpha))
    shaders_list.append(BaseThicknessShader(linestyle.thickness, thickness_position,
                                            linestyle.thickness_ratio))
    for m in linestyle.color_modifiers:
        if not m.use:
            continue
        if m.type == 'ALONG_STROKE':
            shaders_list.append(ColorAlongStrokeShader(
                m.blend, m.influence, m.color_ramp))
        elif m.type == 'DISTANCE_FROM_CAMERA':
            shaders_list.append(ColorDistanceFromCameraShader(
                m.blend, m.influence, m.color_ramp,
                m.range_min, m.range_max))
        elif m.type == 'DISTANCE_FROM_OBJECT':
            shaders_list.append(ColorDistanceFromObjectShader(
                m.blend, m.influence, m.color_ramp, m.target,
                m.range_min, m.range_max))
        elif m.type == 'MATERIAL':
            shaders_list.append(ColorMaterialShader(
                m.blend, m.influence, m.color_ramp, m.material_attribute,
                m.use_ramp))
    for m in linestyle.alpha_modifiers:
        if not m.use:
            continue
        if m.type == 'ALONG_STROKE':
            shaders_list.append(AlphaAlongStrokeShader(
                m.blend, m.influence, m.mapping, m.invert, m.curve))
        elif m.type == 'DISTANCE_FROM_CAMERA':
            shaders_list.append(AlphaDistanceFromCameraShader(
                m.blend, m.influence, m.mapping, m.invert, m.curve,
                m.range_min, m.range_max))
        elif m.type == 'DISTANCE_FROM_OBJECT':
            shaders_list.append(AlphaDistanceFromObjectShader(
                m.blend, m.influence, m.mapping, m.invert, m.curve, m.target,
                m.range_min, m.range_max))
        elif m.type == 'MATERIAL':
            shaders_list.append(AlphaMaterialShader(
                m.blend, m.influence, m.mapping, m.invert, m.curve,
                m.material_attribute))
    for m in linestyle.thickness_modifiers:
        if not m.use:
            continue
        if m.type == 'ALONG_STROKE':
            shaders_list.append(ThicknessAlongStrokeShader(
                thickness_position, linestyle.thickness_ratio,
                m.blend, m.influence, m.mapping, m.invert, m.curve,
                m.value_min, m.value_max))
        elif m.type == 'DISTANCE_FROM_CAMERA':
            shaders_list.append(ThicknessDistanceFromCameraShader(
                thickness_position, linestyle.thickness_ratio,
                m.blend, m.influence, m.mapping, m.invert, m.curve,
                m.range_min, m.range_max, m.value_min, m.value_max))
        elif m.type == 'DISTANCE_FROM_OBJECT':
            shaders_list.append(ThicknessDistanceFromObjectShader(
                thickness_position, linestyle.thickness_ratio,
                m.blend, m.influence, m.mapping, m.invert, m.curve, m.target,
                m.range_min, m.range_max, m.value_min, m.value_max))
        elif m.type == 'MATERIAL':
            shaders_list.append(ThicknessMaterialShader(
                thickness_position, linestyle.thickness_ratio,
                m.blend, m.influence, m.mapping, m.invert, m.curve,
                m.material_attribute, m.value_min, m.value_max))
        elif m.type == 'CALLIGRAPHY':
            shaders_list.append(CalligraphicThicknessShader(
                thickness_position, linestyle.thickness_ratio,
                m.blend, m.influence,
                m.orientation, m.thickness_min, m.thickness_max))
    if linestyle.caps == 'ROUND':
        shaders_list.append(RoundCapShader())
    elif linestyle.caps == 'SQUARE':
        shaders_list.append(SquareCapShader())
    if linestyle.use_dashed_line:
        pattern = []
        if linestyle.dash1 > 0 and linestyle.gap1 > 0:
            pattern.append(linestyle.dash1)
            pattern.append(linestyle.gap1)
        if linestyle.dash2 > 0 and linestyle.gap2 > 0:
            pattern.append(linestyle.dash2)
            pattern.append(linestyle.gap2)
        if linestyle.dash3 > 0 and linestyle.gap3 > 0:
            pattern.append(linestyle.dash3)
            pattern.append(linestyle.gap3)
        if len(pattern) > 0:
            shaders_list.append(DashedLineShader(pattern))
    # create strokes using the shaders list
    Operators.create(TrueUP1D(), shaders_list)