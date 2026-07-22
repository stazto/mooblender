"""Numeric record identifiers observed in PMob binary trees."""

from __future__ import annotations

from enum import IntEnum


class ContentType(IntEnum):
    """Known PMob record identifiers recovered from producer behavior."""

    MESH = 0x00
    MESH_LIST = 0x01
    VERTICES = 0x02
    INDICES = 0x03
    NORMALS = 0x04
    TEXT_COORDS = 0x05
    COLORS = 0x06
    LINE_INDICES = 0x07
    COLOR = 0x08
    NAME = 0x09
    PMOB = 0x0A
    LAYER = 0x0B
    LAYER_LIST = 0x0C
    VERSION = 0x0D
    PRIMITIVE = 0x0E
    POSITION = 0x0F
    ROTATION = 0x10
    SCALE = 0x11
    PRIMITIVE_TYPE = 0x12
    LAYER_REF = 0x13
    PRIMITIVES_LIST = 0x14
    MATRIX = 0x15
    MESH_SOURCE_TYPE = 0x16
    ANIMATION = 0x17
    ANIMATION_TIME_LIST = 0x18
    ANIMATION_TRANSFORM_LIST = 0x19
    MATERIAL = 0x1A
    MATERIAL_LIST = 0x1B
    MATERIAL_ID = 0x1C
    SPECULAR_COLOR = 0x1D
    SPECULAR_POWER = 0x1F
    REFLECTION_MAX = 0x20
    OPACITY = 0x21
    DIFFUSE_TEXTURE = 0x22
    SPECULAR_TEXTURE = 0x23
    NORMAL_TEXTURE = 0x24
    SMOOTH_GROUPS = 0x25
    AMBIENT_INTENSITY = 0x26
    MAPPING_TYPE = 0x27
    MAPPING_SCALE = 0x28
    MAPPING_NUMBER = 0x29
    MAPPING_ROTATION = 0x2A
    METALLIC = 0x2B
    REFLECTION_MIN = 0x2C
    ROUGHNESS = 0x2D
    BORDER_COLOR = 0x2E
    BORDER_WIDTH = 0x2F
    MIRROR = 0x30
    DIFFUSE = 0x31
    CRAND = 0x32
    EMISSION = 0x33
    CONSERVE_ENERGY = 0x34
    APPLY_TEXTURE_IN_FRAMES = 0x35
    TRANSLUCENCY = 0x36
    FRESNEL_TERM = 0x37
    REFRACTION_FACTOR = 0x38
