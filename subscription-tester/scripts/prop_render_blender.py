"""Blender worker for prop_models: render one posed mesh to a transparent PNG.

Usage: blender --background --factory-startup --python prop_render_blender.py -- JOB.json
Camera at the origin looking down -Z, +Y up (Blender's camera convention), same matrix
and field of view as the VTK worker. Soft area light, white matte plastic.
"""
import json
import math
import sys

import bpy
from mathutils import Matrix, Vector

job = json.loads(open(sys.argv[sys.argv.index('--') + 1]).read())
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

if job['format'] == 'stl':
    bpy.ops.wm.stl_import(filepath=job['mesh'])
else:
    bpy.ops.wm.obj_import(filepath=job['mesh'], forward_axis='NEGATIVE_Z', up_axis='Y')
obj = bpy.context.selected_objects[0]
obj.matrix_world = Matrix(job['matrix'])
bpy.context.view_layer.objects.active = obj
bpy.ops.object.shade_auto_smooth(angle=math.radians(35)) if hasattr(bpy.ops.object, 'shade_auto_smooth') else None

material = bpy.data.materials.new('PropWhite')
material.use_nodes = True
shader = material.node_tree.nodes.get('Principled BSDF')
shader.inputs['Base Color'].default_value = (*job['color'], 1)
shader.inputs['Roughness'].default_value = 0.45
obj.data.materials.append(material)

camera = bpy.data.objects.new('Camera', bpy.data.cameras.new('Camera'))
scene.collection.objects.link(camera)
camera.matrix_world = Matrix.Identity(4)
camera.data.sensor_fit = 'VERTICAL'
camera.data.angle = math.radians(job['vfov_deg'])
camera.data.clip_start = 0.001
camera.data.clip_end = 10000
scene.camera = camera

light = job.get('light') or {}
key_color = light.get('key_color', [1, 1, 1])
key_strength = light.get('key_strength', 4.5)
key_direction = light.get('key_direction', [1.2, 1.4, 0.6])
# Soft sun lights: key (configurable), fill from the left, rim from behind. The same at any distance.
for name, strength, direction, angle, color in (('Key', key_strength, key_direction, 25, key_color),
                                                ('Fill', key_strength * 0.22, (-1.4, 0.3, 0.8), 40, light.get('ambient_color', [1, 1, 1])),
                                                ('Rim', key_strength * 0.27, (0.2, 1.6, -1.2), 15, [1, 1, 1])):
    data = bpy.data.lights.new(name, 'SUN')
    data.energy = strength
    data.angle = math.radians(angle)
    data.color = color
    item = bpy.data.objects.new(name, data)
    scene.collection.objects.link(item)
    item.rotation_euler = Vector(direction).normalized().to_track_quat('Z', 'Y').to_euler()

world = bpy.data.worlds.new('World')
world.use_nodes = True
world.node_tree.nodes['Background'].inputs['Color'].default_value = (*light.get('ambient_color', [0.8, 0.81, 0.83]), 1)
world.node_tree.nodes['Background'].inputs['Strength'].default_value = light.get('ambient_strength', 0.35)
scene.world = world

engines = [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items]
shadow = job.get('ground_shadow', False)
scene.render.engine = 'CYCLES' if shadow else next(e for e in ('BLENDER_EEVEE', 'BLENDER_EEVEE_NEXT', 'CYCLES') if e in engines)
if scene.render.engine == 'CYCLES':
    scene.cycles.samples = 96
    scene.cycles.use_denoising = True
    scene.cycles.device = 'CPU'

if shadow:
    # A shadow-catching ground under the model: perpendicular to the model's own up axis, at its lowest point.
    up = (Matrix(job['matrix']).to_3x3() @ Vector(job.get('up_vector', (0, 0, 1)))).normalized()
    lowest = min((obj.matrix_world @ v.co).dot(up) for v in obj.data.vertices)
    bpy.ops.mesh.primitive_plane_add(size=1)
    ground = bpy.context.active_object
    center = obj.matrix_world.translation
    ground.location = center - up * (center.dot(up) - lowest)
    ground.rotation_euler = up.to_track_quat('Z', 'Y').to_euler()
    ground.scale = (50, 50, 1)
    ground.is_shadow_catcher = True
scene.render.film_transparent = True
scene.render.resolution_x = job['width']
scene.render.resolution_y = job['height']
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGBA'
for transform in ('AgX', 'Filmic', 'Standard'):
    try:
        scene.view_settings.view_transform = transform
        break
    except TypeError:
        continue
scene.view_settings.exposure = light.get('exposure', 0.0)
scene.render.filepath = job['output']
bpy.ops.render.render(write_still=True)
