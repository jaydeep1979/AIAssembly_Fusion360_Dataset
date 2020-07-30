import adsk.core
import adsk.fusion
import traceback
import json
import os
import sys
import time
import copy
from pathlib import Path
from importlib import reload


# Add the common folder to sys.path
COMMON_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "common"))
if COMMON_DIR not in sys.path:
    sys.path.append(COMMON_DIR)

import name
import exporter
import serialize
import exceptions
from logger import Logger
from sketch_extrude_importer import SketchExtrudeImporter
reload(serialize)


# Event handlers
handlers = []


class OnlineStatusChangedHandler(adsk.core.ApplicationEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        # Start the server when onlineStatusChanged handler returns
        start()


class Regraph():
    """Reconstruction Graph
        Takes a reconstruction json file and converts it
        into a graph representing B-Rep topology"""

    def __init__(self, json_file, logger):
        self.json_file = json_file
        self.logger = logger
        # References to the Fusion design
        self.app = adsk.core.Application.get()
        self.design = adsk.fusion.Design.cast(self.app.activeProduct)
        self.product = self.app.activeProduct
        self.timeline = self.app.activeProduct.timeline
        # Cache of the extrude face label information
        self.face_cache = {}
        # Cache of the edge information
        self.edge_cache = {}
        # The sequence of nodes and edges that become explained
        self.sequence = []
        # The cache of the faces and edges seen so far
        self.sequence_cache = {
            "faces": set(),
            "edges": set()
        }
        # Current extrude index
        self.current_extrude_index = 0
        # Current overall action index
        self.current_action_index = 0
        # The mode we want
        self.mode = "PerExtrude"
        # self.mode = "PerFace"

    # -------------------------------------------------------------------------
    # EXPORT
    # -------------------------------------------------------------------------

    def export(self, output_dir, results_file, results):
        """Reconstruct the design from the json file"""
        self.output_dir = output_dir
        self.results = results
        self.results_file = results_file
        # Immediately log this in case we crash
        self.results[self.json_file.name] = []
        self.save_results()
        importer = SketchExtrudeImporter(self.json_file)
        self.extrude_count = self.get_extrude_count(importer.data)
        importer.reconstruct()
        # After reconstruction, iterate over the timeline and populate the face cache
        for timeline_object in self.timeline:
            if isinstance(timeline_object.entity, adsk.fusion.ExtrudeFeature):
                self.add_extrude_to_cache(timeline_object.entity)
        # Check that all faces have uuids
        for body in self.design.rootComponent.bRepBodies:
            for face in body.faces:
                face_uuid = name.get_uuid(face)
                assert face_uuid is not None
        prev_extrude_index = 0
        # Next move the marker to after each extrude and export
        for timeline_object in self.timeline:
            if isinstance(timeline_object.entity, adsk.fusion.ExtrudeFeature):
                self.timeline.markerPosition = timeline_object.index + 1
                extrude = timeline_object.entity
                export_supported = self.is_supported_export(extrude)
                if not export_supported:
                    self.timeline.markerPosition = prev_extrude_index
                    break
                # Populate the cache again
                self.add_extrude_to_cache(extrude)
                self.add_extrude_edges_to_cache()
                self.inc_export_extrude(extrude)
                prev_extrude_index = self.timeline.markerPosition
        self.last_export()

    def is_supported_export(self, extrude):
        """Check if this is a supported state for export"""
        if extrude.operation == adsk.fusion.FeatureOperations.IntersectFeatureOperation:
            self.logger.log(f"Skipping {extrude.name}: Extrude has intersect operation")
            return False
        if self.is_extrude_tapered(extrude):
            self.logger.log(f"Skipping {extrude.name}: Extrude has taper")
            return False
        if self.mode == "PerFace":
            # If we have a cut/intersect operation we want to use what we have
            # and export it
            if extrude.operation == adsk.fusion.FeatureOperations.CutFeatureOperation:
                self.logger.log(f"Skipping {extrude.name}: Extrude has cut operation")
                return False
            # If we don't have a single extrude start/end face
            if extrude.endFaces.count != 1 and extrude.startFaces.count != 1:
                self.logger.log(f"Skipping {extrude.name}: Extrude doesn't have a single start or end face")
                return False
            # # If we don't have an end face
            # if extrude.endFaces.count == 0:
            #     self.logger.log(f"Skipping {extrude.name}: Extrude end faces == 0")
            #     return False
        return True

    def inc_export_extrude(self, extrude):
        """Save out a graph after each extrude as reconstruction takes place"""
        # If we are exporting per curve
        if self.mode == "PerFace":
            self.add_extrude_to_sequence(extrude)
        elif self.mode == "PerExtrude":
            self.export_extrude_graph()
        self.current_extrude_index += 1

    def last_export(self):
        """Export after the full reconstruction"""
        # The last extrude
        if self.mode == "PerFace":
            # Only export if we had some valid extrudes
            if self.current_extrude_index > 0:
                self.export_extrude_graph()
                self.export_sequence()

    def get_export_path(self, name):
        """Get the export path from a name"""
        return self.output_dir / f"{self.json_file.stem}_{name}.json"

    def export_extrude_graph(self):
        """Export a graph from an extrude operation"""
        graph = self.get_graph()
        if self.mode == "PerFace":
            graph_file = self.get_export_path("target")
        else:
            graph_file = self.get_export_path(f"{self.current_extrude_index:04}")
        self.export_graph(graph_file, graph)

    def export_graph(self, graph_file, graph):
        """Export a graph as json"""
        self.logger.log(f"Exporting {graph_file}")
        exporter.export_json(graph_file, graph)
        if graph_file.exists():
            self.results[self.json_file.name].append(graph_file.name)
            self.save_results()
        else:
            self.logger.log(f"Error exporting {graph_file}")

    def export_sequence(self):
        """Export the sequence data"""
        seq_file = self.output_dir / f"{self.json_file.stem}_sequence.json"
        seq_data = {
            "sequence": self.sequence,
            "properties": {
                "bounding_box": serialize.bounding_box3d(
                    self.design.rootComponent.boundingBox)
            }
        }
        with open(seq_file, "w", encoding="utf8") as f:
            json.dump(seq_data, f, indent=4)

    def save_results(self):
        """Save out the results of conversion"""
        with open(self.results_file, "w", encoding="utf8") as f:
            json.dump(self.results, f, indent=4)

    def get_extrude_count(self, data):
        """Get the number of extrudes in a design"""
        extrude_count = 0
        entities = data["entities"]
        for entity in entities.values():
            if entity["type"] == "ExtrudeFeature":
                extrude_count += 1
        return extrude_count

    # -------------------------------------------------------------------------
    # DATA CACHING
    # -------------------------------------------------------------------------

    def get_temp_ids_from_collection(self, collection):
        """From a collection, make a set of the tempids"""
        id_set = set()
        for entity in collection:
            if entity is not None:
                temp_id = entity.tempId
                id_set.add(temp_id)
        return id_set

    def get_extrude_operation(self, extrude_operation):
        """Get the extrude operation as short string and regular string"""
        operation = serialize.feature_operation(extrude_operation)
        operation_short = operation.replace("FeatureOperation", "")
        assert operation_short != "NewComponent"
        if operation_short == "NewBody" or operation_short == "Join":
            operation_short = "Extrude"
        return operation, operation_short

    def add_extrude_to_cache(self, extrude):
        """Add the data from the latest extrude to the cache"""
        # First toggle the previous extrude last_operation label
        for face_data in self.face_cache.values():
            face_data["last_operation_label"] = False
        operation, operation_short = self.get_extrude_operation(extrude.operation)
        self.add_extrude_faces_to_cache(extrude.startFaces, operation_short, "Start")
        self.add_extrude_faces_to_cache(extrude.endFaces, operation_short, "End")
        self.add_extrude_faces_to_cache(extrude.sideFaces, operation_short, "Side")

    def add_extrude_faces_to_cache(self, extrude_faces, operation_short, extrude_face_location):
        """Update the extrude face cache with the recently added faces"""
        for face in extrude_faces:
            face_uuid = name.set_uuid(face)
            assert face_uuid is not None
            # We will have split faces with the same uuid
            # So we need to update them
            # assert face_uuid not in self.face_cache
            self.face_cache[face_uuid] = {
                # "timeline_label": self.current_extrude_index / self.extrude_count,
                "operation_label": f"{operation_short}{extrude_face_location}",
                "last_operation_label": True
            }

    def add_extrude_edges_to_cache(self):
        """Update the edge cache with the latest extrude"""
        concave_edge_cache = set()
        for body in self.design.rootComponent.bRepBodies:
            temp_ids = self.get_temp_ids_from_collection(body.concaveEdges)
            concave_edge_cache.update(temp_ids)
        for body in self.design.rootComponent.bRepBodies:
            for face in body.faces:
                for edge in face.edges:
                    assert edge.faces.count == 2
                    edge_uuid = name.set_uuid(edge)
                    edge_concave = edge.tempId in concave_edge_cache
                    assert edge_uuid is not None
                    self.edge_cache[edge_uuid] = {
                        "temp_id": edge.tempId,
                        "convexity": self.get_edge_convexity(edge, edge_concave),
                        "source": name.get_uuid(edge.faces[0]),
                        "target": name.get_uuid(edge.faces[1])
                    }

    def add_extrude_to_sequence(self, extrude):
        """Add the extrude operation to the sequence"""
        # Look for a start or end face with a single face
        if extrude.startFaces.count == 1:
            print("Extruding from start face")
            start_face = extrude.startFaces[0]
            end_faces = extrude.endFaces
            start_end_flipped = False
        elif extrude.endFaces.count == 1:
            print("Extruding from end face")
            start_face = extrude.endFaces[0]
            end_faces = extrude.startFaces
            start_end_flipped = True
        assert start_face is not None
        start_face_uuid = name.get_uuid(start_face)
        assert start_face_uuid is not None
        print(f"Start face: {start_face.tempId}")
        # Add the face and edges that we extrude from
        self.sequence_cache["faces"].add(start_face_uuid)
        for edge in start_face.edges:
            edge_uuid = name.get_uuid(edge)
            assert edge_uuid is not None
            self.sequence_cache["edges"].add(edge_uuid)
        extrude_from_sequence_entry = {
            "action": start_face_uuid,
            "faces": list(self.sequence_cache["faces"]),
            "edges": list(self.sequence_cache["edges"])
        }
        self.sequence.append(extrude_from_sequence_entry)

        if end_faces.count > 0:
            # If we have a face to extrude to, lets use it
            end_face = end_faces[0]
        else:
            # Or we need to find an end face to extrude to
            # that is on coplanar to the end of the extrude
            if start_end_flipped:
                end_plane = self.get_extrude_start_plane(extrude)
            else:
                end_plane = self.get_extrude_end_plane(extrude)
            # Search for faces that are coplanar
            end_face = self.get_coplanar_face(end_plane)
        assert end_face is not None
        end_face_uuid = name.get_uuid(end_face)
        assert end_face_uuid is not None
        print(f"End face: {end_face.tempId}")
        # Add the face and edges for everything that was extruded
        for face in extrude.faces:
            face_uuid = name.get_uuid(face)
            assert face_uuid is not None
            self.sequence_cache["faces"].add(face_uuid)
            for edge in face.edges:
                edge_uuid = name.get_uuid(edge)
                assert edge_uuid is not None
                self.sequence_cache["edges"].add(edge_uuid)
        extrude_to_sequence_entry = {
            "action": end_face_uuid,
            "faces": list(self.sequence_cache["faces"]),
            "edges": list(self.sequence_cache["edges"])
        }
        self.sequence.append(extrude_to_sequence_entry)

    # -------------------------------------------------------------------------
    # FEATURES
    # -------------------------------------------------------------------------

    def get_face_normal(self, face):
        point_on_face = face.pointOnFace
        evaluator = face.evaluator
        normal_result, normal = evaluator.getNormalAtPoint(point_on_face)
        assert normal_result
        return normal

    def are_faces_tangentially_connected(self, face1, face2):
        for tc_face in face1.tangentiallyConnectedFaces:
            if tc_face.tempId == face2.tempId:
                return True
        return False

    def are_faces_perpendicular(self, face1, face2):
        normal1 = self.get_face_normal(face1)
        normal2 = self.get_face_normal(face2)
        return normal1.isPerpendicularTo(normal2)

    def get_edge_convexity(self, edge, is_concave):
        # is_concave = self.is_concave_edge(edge.tempId)
        is_tc = self.are_faces_tangentially_connected(edge.faces[0], edge.faces[1])
        convexity = "Convex"
        # edge_data["convex"] = self.is_convex_edge(edge.tempId)
        if is_concave:
            convexity = "Concave"
        elif is_tc:
            convexity = "Smooth"
        return convexity

    def linspace(self, start, stop, n):
        if n == 1:
            yield stop
            return
        h = (stop - start) / (n - 1)
        for i in range(n):
            yield start + h * i

    def get_edge_parameter_features(self, edge):
        param_features = {}
        samples = 10
        evaluator = edge.evaluator
        result, start_param, end_param = evaluator.getParameterExtents()
        assert result
        parameters = list(self.linspace(start_param, end_param, samples))
        result, points = evaluator.getPointsAtParameters(parameters)
        assert result
        param_features["param_points"] = []
        for pt in points:
            param_features["param_points"].append(pt.x)
            param_features["param_points"].append(pt.y)
            param_features["param_points"].append(pt.z)
        return param_features

    # -------------------------------------------------------------------------
    # FILTER
    # -------------------------------------------------------------------------

    def is_extrude_tapered(self, extrude):
        if extrude.extentOne is not None:
            if isinstance(extrude.extentOne, adsk.fusion.DistanceExtentDefinition):
                if extrude.taperAngleOne is not None:
                    if extrude.taperAngleOne.value is not None and extrude.taperAngleOne.value != "":
                        if extrude.taperAngleOne.value != 0:
                            return True
        # Check the second extent if needed
        if (extrude.extentType ==
                adsk.fusion.FeatureExtentTypes.TwoSidesFeatureExtentType):
            if extrude.extentTwo is not None:
                if isinstance(extrude.extentTwo, adsk.fusion.DistanceExtentDefinition):
                    if extrude.taperAngleTwo is not None:
                        if extrude.taperAngleTwo.value is not None and extrude.taperAngleTwo.value != "":
                            if extrude.taperAngleTwo.value != 0:
                                return True
        return False

    # -------------------------------------------------------------------------
    # GRAPH CONSTRUCTION
    # -------------------------------------------------------------------------

    def get_empty_graph(self):
        """Get an empty graph to start"""
        return {
            "directed": False,
            "multigraph": False,
            "graph": {},
            "nodes": [],
            "links": []
        }

    def get_graph(self):
        """Get a graph data structure for bodies"""
        graph = self.get_empty_graph()
        for body in self.design.rootComponent.bRepBodies:
            for face in body.faces:
                if face is not None:
                    face_data = self.get_face_data(face)
                    graph["nodes"].append(face_data)

            for edge in body.edges:
                if edge is not None:
                    edge_data = self.get_edge_data(edge)
                    graph["links"].append(edge_data)
        return graph

    def get_face_data(self, face):
        """Get the features for a face"""
        face_uuid = name.get_uuid(face)
        assert face_uuid is not None
        face_metadata = self.face_cache[face_uuid]
        if self.mode == "PerExtrude":
            return self.get_face_data_per_extrude(face, face_uuid, face_metadata)
        elif self.mode == "PerFace":
            return self.get_face_data_per_face(face, face_uuid, face_metadata)

    def get_common_face_data(self, face, face_uuid):
        """Get common edge data"""
        face_data = {}
        face_data["id"] = face_uuid
        return face_data

    def get_face_data_per_extrude(self, face, face_uuid, face_metadata):
        """Get the features for a face for a per extrude graph"""
        face_data = self.get_common_face_data(face, face_uuid)
        face_data["surface_type"] = serialize.surface_type(face.geometry)
        # face_data["surface_type_id"] = face.geometry.surfaceType
        face_data["area"] = face.area
        normal = self.get_face_normal(face)
        face_data["normal_x"] = normal.x
        face_data["normal_y"] = normal.y
        face_data["normal_z"] = normal.z
        # face_data["normal_length"] = normal.length
        parameter_result, parameter_at_point = face.evaluator.getParameterAtPoint(face.pointOnFace)
        assert parameter_result
        curvature_result, max_tangent, max_curvature, min_curvature = face.evaluator.getCurvature(parameter_at_point)
        assert curvature_result
        face_data["max_tangent_x"] = max_tangent.x
        face_data["max_tangent_y"] = max_tangent.y
        face_data["max_tangent_z"] = max_tangent.z
        # face_data["max_tangent_length"] = max_tangent.length
        face_data["max_curvature"] = max_curvature
        face_data["min_curvature"] = min_curvature
        # face_data["timeline_label"] = face_metadata["timeline_label"]
        face_data["operation_label"] = face_metadata["operation_label"]
        face_data["last_operation_label"] = face_metadata["last_operation_label"]
        return face_data

    def get_face_data_per_face(self, face, face_uuid, face_metadata):
        """Get the features for a face for a per curve graph"""
        face_data = self.get_common_face_data(face, face_uuid)
        return face_data

    def get_edge_data(self, edge):
        """Get the features for an edge"""
        edge_uuid = name.get_uuid(edge)
        assert edge_uuid is not None
        edge_metadata = self.edge_cache[edge_uuid]
        if self.mode == "PerExtrude":
            return self.get_edge_data_per_extrude(edge, edge_uuid, edge_metadata)
        elif self.mode == "PerFace":
            return self.get_edge_data_per_face(edge, edge_uuid, edge_metadata)

    def get_common_edge_data(self, edge_uuid, edge_metadata):
        """Get common edge data"""
        edge_data = {}
        edge_data["id"] = edge_uuid
        edge_data["source"] = edge_metadata["source"]
        edge_data["target"] = edge_metadata["target"]
        return edge_data

    def get_edge_data_per_extrude(self, edge, edge_uuid, edge_metadata):
        """Get the features for an edge for a per extrude graph"""
        edge_data = self.get_common_edge_data(edge_uuid, edge_metadata)
        edge_data["curve_type"] = serialize.curve_type(edge.geometry)
        # edge_data["curve_type_id"] = edge.geometry.curveType
        edge_data["length"] = edge.length
        # Create a feature for the edge convexity
        edge_data["convexity"] = edge_metadata["convexity"]
        edge_data["perpendicular"] = self.are_faces_perpendicular(edge.faces[0], edge.faces[1])
        point_on_edge = edge.pointOnEdge
        evaluator = edge.evaluator
        parameter_result, parameter_at_point = evaluator.getParameterAtPoint(point_on_edge)
        assert parameter_result
        curvature_result, direction, curvature = evaluator.getCurvature(parameter_at_point)
        edge_data["direction_x"] = direction.x
        edge_data["direction_y"] = direction.y
        edge_data["direction_z"] = direction.z
        # edge_data["direction_length"] = direction.length
        edge_data["curvature"] = curvature
        return edge_data

    def get_edge_data_per_face(self, edge, edge_uuid, edge_metadata):
        """Get the features for an edge for a per curve graph"""
        edge_data = self.get_common_edge_data(edge_uuid, edge_metadata)
        edge_param_feat = self.get_edge_parameter_features(edge)
        edge_data.update(edge_param_feat)
        return edge_data

    def get_extrude_start_plane(self, extrude):
        """Get the plane where the extrude starts"""
        extrude_offset = self.get_extrude_offset(extrude)
        sketch = extrude.profile.parentSketch
        sketch_normal = extrude.profile.plane.normal
        sketch_normal.transformBy(sketch.transform)
        sketch_origin = sketch.origin
        if extrude_offset != 0:
            sketch_origin = self.offset_point_by_distance(sketch_origin, sketch_normal, extrude_offset)
        return adsk.core.Plane.create(sketch_origin, sketch_normal)

    def get_extrude_end_plane(self, extrude):
        """Get the plane where the extrude ends"""
        plane = self.get_extrude_start_plane(extrude)
        extrude_distance = self.get_extrude_distance(extrude)
        plane.origin = self.offset_point_by_distance(plane.origin, plane.normal, extrude_distance)
        return plane

    def offset_point_by_distance(self, point, vector, distance):
        """Offset a point along a vector by a given distance"""
        point_vector = point.asVector()
        scale_vector = vector.copy()
        scale_vector.scaleBy(distance)
        point_vector.add(scale_vector)
        return point_vector.asPoint()

    def get_extrude_distance(self, extrude):
        """Get the extrude distance"""
        if extrude.extentType != adsk.fusion.FeatureExtentTypes.OneSideFeatureExtentType:
            raise exceptions.UnsupportedException(f"Unsupported Extent Type: {extrude.extentType}")
        if not isinstance(extrude.extentOne, adsk.fusion.DistanceExtentDefinition):
            raise exceptions.UnsupportedException(f"Unsupported Extent Definition: {extrude.extentOne.objectType}")
        return extrude.extentOne.distance.value

    def get_extrude_offset(self, extrude):
        """Get any offset from the sketch plane to the extrude"""
        start_extent = extrude.startExtent
        if isinstance(start_extent, adsk.fusion.ProfilePlaneStartDefinition):
            return 0
        elif isinstance(start_extent, adsk.fusion.OffsetStartDefinition):
            offset = start_extent.offset
            # If the ProfilePlaneWithOffsetDefinition is
            # associated with an existing feature
            if isinstance(offset, adsk.fusion.ModelParameter):
                return offset.value
            # If the ProfilePlaneWithOffsetDefinition object was created statically
            # and is not associated with a feature
            elif isinstance(offset, adsk.core.ValueInput):
                if offset.valueType == adsk.fusion.ValueTypes.RealValueType:
                    return offset.realValue
                elif value_input.valueType == adsk.fusion.ValueTypes.StringValueType:
                    return float(offset.stringValue)
        return 0

    def get_coplanar_face(self, plane):
        """Find a face that is coplanar to the given plane"""
        for body in self.design.rootComponent.bRepBodies:
            for face in body.faces:
                if isinstance(face.geometry, adsk.core.Plane):
                    is_coplanar = plane.isCoPlanarTo(face.geometry)
                    if is_coplanar:
                        return face
        return None


# -------------------------------------------------------------------------
# RUNNING
# -------------------------------------------------------------------------


def load_results(results_file):
    """Load the results of conversion"""
    if results_file.exists():
        with open(results_file, "r", encoding="utf8") as f:
            return json.load(f)
    return {}


def start():
    app = adsk.core.Application.get()
    # Logger to print to the text commands window in Fusion
    logger = Logger()
    # Fusion requires an absolute path
    current_dir = Path(__file__).resolve().parent
    data_dir = current_dir.parent / "testdata"
    output_dir = current_dir / "output"
    if not output_dir.exists():
        output_dir.mkdir(parents=True)

    results_file = output_dir / "regraph_results.json"
    results = load_results(results_file)

    # Get all the files in the data folder
    # json_files = [f for f in data_dir.glob("**/*_[0-9][0-9][0-9][0-9].json")]
    json_files = [
        data_dir / "Couch.json",
        # data_dir / "SingleSketchExtrude_RootComponent.json",
        # data_dir / "regraph/Z0StepHighAtOrig_12e50ae9_0000.json"
    ]

    json_count = len(json_files)
    for i, json_file in enumerate(json_files, start=1):
        # if json_file.name in results:
        #     logger.log(f"[{i}/{json_count}] Skipping {json_file}")
        # else:
        try:
            logger.log(f"[{i}/{json_count}] Processing {json_file}")
            reconverter = Regraph(json_file, logger)
            reconverter.export(output_dir, results_file, results)

        except Exception as ex:
            logger.log(f"Error reconstructing: {ex}")
            logger.log(traceback.format_exc())
        finally:
            # Close the document
            # Fusion automatically opens a new window
            # after the last one is closed
            app.activeDocument.close(False)


def run(context):
    try:
        app = adsk.core.Application.get()
        # If we have started manually
        # we go ahead and startup
        if app.isStartupComplete:
            start()
        else:
            # If we are being started on startup
            # then we subscribe to ‘onlineStatusChanged’ event
            # This event is triggered on Fusion startup
            print("Setting up online status changed handler...")
            on_online_status_changed = OnlineStatusChangedHandler()
            app.onlineStatusChanged.add(on_online_status_changed)
            handlers.append(on_online_status_changed)

    except:
        print(traceback.format_exc())