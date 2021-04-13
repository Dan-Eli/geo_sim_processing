# -*- coding: utf-8 -*-
# pylint: disable=no-name-in-module
# pylint: disable=too-many-lines
# pylint: disable=useless-return
# pylint: disable=too-few-public-methods

# /***************************************************************************
# simplify_algorithm.py
# ----------
# Date                 : April 2021
# copyright            : (C) 2020 by Natural Resources Canada
# email                : daniel.pilon@canada.ca
#
#  ***************************************************************************/
#
# /***************************************************************************
#  *                                                                         *
#  *   This program is free software; you can redistribute it and/or modify  *
#  *   it under the terms of the GNU General Public License as published by  *
#  *   the Free Software Foundation; either version 2 of the License, or     *
#  *   (at your option) any later version.                                   *
#  *                                                                         *
#  ***************************************************************************/

"""
QGIS Plugin for Simplification (Douglas-Peucker algorithm)
"""

from .geo_sim_util import Epsilon, GsCollection, GsFeature, GsPolygon, GsLineString, GsPoint, GeoSimUtil
import os
import inspect
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.core import (QgsProcessing, QgsProcessingAlgorithm, QgsProcessingParameterDistance,
                       QgsProcessingParameterFeatureSource, QgsProcessingParameterFeatureSink,
                       QgsProcessingParameterBoolean, QgsFeatureSink, QgsFeatureRequest,
                       QgsLineString, QgsPolygon, QgsWkbTypes, QgsGeometry, QgsProcessingException)
import processing


class SimplifyAlgorithm(QgsProcessingAlgorithm):
    """Main class defining the Reduce Bend as a QGIS processing algorithm.
    """

    def tr(self, string):  # pylint: disable=no-self-use
        """Returns a translatable string with the self.tr() function.
        """
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):  # pylint: disable=no-self-use
        """Returns a new copy of the algorithm.
        """
        return SimplifyAlgorithm()

    def name(self):  # pylint: disable=no-self-use
        """Returns the unique algorithm name.
        """
        return 'simplify'

    def displayName(self):  # pylint: disable=no-self-use
        """Returns the translated algorithm name.
        """
        return self.tr('Simplify')

    def group(self):
        """Returns the name of the group this algorithm belongs to.
        """
        return self.tr(self.groupId())

    def groupId(self):  # pylint: disable=no-self-use
        """Returns the unique ID of the group this algorithm belongs to.
        """
        return ''

    def shortHelpString(self):
        """Returns a localised short help string for the algorithm.
        """
        help_str = """
    Simplify is a geospatial simplification and generalization tool for lines and polygons. The \
    particularity of this algorithm is that for each line or polygon it analyzes its bends (curves) and \
    decides which one to reduce, trying to emulate what a cartographer would do manually \
    to simplify or generalize a line. Reduce bend will accept lines and polygons as input.  Reduce bend will \
    preserve the topology (spatial relations) within and between the features during the bend reduction. \
    Reduce bend also accept multi lines and multi polygons but will output lines and polygons.

    <b>Usage</b>
    <u>Input layer</u> : Any LineString or Polygon layer.  Multi geometry are transformed into single part geometry.
    <u>Tolerance</u>: Tolerance used for line simplification.
    <u>Simplified</u> : Output layer of the algorithm.

    <b>Rule of thumb for the diameter tolerance</b>
    Reduce bend can be used for line simplifying in the context of line generalization. The big \
    question will often be what diameter should we use? A good starting point is the cartographic rule of \
    thumb -- the .5mm on the map -- which says that the minimum distance between two lines should be \
    greater than 0.5mm on a paper map. So to simplify (generalize) a line for representation at a scale of \
    1:50 000 for example a diameter of 25m should be a good starting point

    """

        return self.tr(help_str)

    def icon(self):  # pylint: disable=no-self-use
        """Define the logo of the algorithm.
        """

        cmd_folder = os.path.split(inspect.getfile(inspect.currentframe()))[0]
        icon = QIcon(os.path.join(os.path.join(cmd_folder, 'logo.png')))
        return icon

    def initAlgorithm(self, config=None):  # pylint: disable=unused-argument
        """Define the inputs and outputs of the algorithm.
        """

        # 'INPUT' is the recommended name for the main input parameter.
        self.addParameter(QgsProcessingParameterFeatureSource(
                          'INPUT',
                          self.tr('Input layer'),
                          types=[QgsProcessing.TypeVectorAnyGeometry]))

        # 'TOLERANCE' to be used bor bend reduction
        self.addParameter(QgsProcessingParameterDistance(
                          'TOLERANCE',
                          self.tr('Diameter tolerance'),
                          defaultValue=0.0,
                          parentParameterName='INPUT'))  # Make distance units match the INPUT layer units

        # 'OUTPUT' for the results
        self.addParameter(QgsProcessingParameterFeatureSink(
                          'OUTPUT',
                          self.tr('Simplified')))

    def processAlgorithm(self, parameters, context, feedback):
        """Main method that extract parameters and call ReduceBend algorithm.
        """

        context.setInvalidGeometryCheck(QgsFeatureRequest.GeometryNoCheck)

        # Extract parameter
        source_in = self.parameterAsSource(parameters, "INPUT", context)
        tolerance = self.parameterAsDouble(parameters, "TOLERANCE", context)
        validate_structure = self.parameterAsBool(parameters, "VALIDATE_STRUCTURE", context)

        if source_in is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, "INPUT"))

        # Transform the in source into a vector layer
        vector_layer_in = source_in.materialize(QgsFeatureRequest(), feedback)

        # Normalize and extract QGS input features
        qgs_features_in, geom_type = Simplify.normalize_in_vector_layer(vector_layer_in, feedback)

        # Validate input geometry type
        if geom_type not in (QgsWkbTypes.LineString, QgsWkbTypes.Polygon):
            raise QgsProcessingException("Can only process: (Multi)LineString or (Multi)Polygon vector layers")

        (sink, dest_id) = self.parameterAsSink(parameters, "OUTPUT", context,
                                               vector_layer_in.fields(),
                                               geom_type,
                                               vector_layer_in.sourceCrs())

        # Validate sink
        if sink is None:
            raise QgsProcessingException(self.invalidSinkError(parameters, "OUTPUT"))

        # Set progress bar to 1%
        feedback.setProgress(1)

        # Call ReduceBend algorithm
        rb_return = Simplify.douglas_peucker(qgs_features_in, tolerance, validate_structure, feedback)

        for qgs_feature_out in rb_return.qgs_features_out:
            sink.addFeature(qgs_feature_out, QgsFeatureSink.FastInsert)

        # Push some output statistics
        feedback.pushInfo(" ")
        feedback.pushInfo("Number of features in: {0}".format(rb_return.in_nbr_features))
        feedback.pushInfo("Number of features out: {0}".format(rb_return.out_nbr_features))
        feedback.pushInfo("Number of iteration needed: {0}".format(rb_return.nbr_pass))
        feedback.pushInfo("Total vertice deleted: {0}".format(rb_return.nbr_vertice_deleted))
        if validate_structure:
            if rb_return.is_structure_valid:
                status = "Valid"
            else:
                status = "Invalid"
            feedback.pushInfo("Debug - State of the internal data structure: {0}".format(status))

        return {"OUTPUT": dest_id}


# --------------------------------------------------------
# Start of the algorithm
# --------------------------------------------------------

# Define global constant


class RbResults:
    """Class defining the stats and result"""

    __slots__ = ('in_nbr_features', 'out_nbr_features', 'nbr_vertice_deleted',  'qgs_features_out', 'nbr_pass',
                 'is_structure_valid')

    def __init__(self):
        """Constructor that initialize a RbResult object.

        :param: None
        :return: None
        :rtype: None
        """

        self.in_nbr_features = None
        self.out_nbr_features = None
        self.nbr_vertice_deleted = 0
        self.qgs_features_out = None
        self.nbr_pass = 0
        self.is_structure_valid = None


class Simplify:
    """Main class for bend reduction"""

    @staticmethod
    def normalize_in_vector_layer(in_vector_layer, feedback):
        """Method used to normalize the input vector layer

        Two processing are used to normalized the input vector layer
         - execute "Multi to single part" processing in order to accept even multipolygon
         - execute "Drop  Z and M values" processing as they are not useful
         - Validate if the resulting layer is Point LineString or Polygon

        :param in_vector_layer:  Input vector layer to normalize
        :param feedback: QgsFeedback handle used to communicate with QGIS
        :return Output vector layer and Output geometry type
        :rtype Tuple of 2 values
        """

        # Execute MultiToSinglePart processing
        feedback.pushInfo("Start normalizing input layer")
        params = {'INPUT': in_vector_layer,
                  'OUTPUT': 'memory:'}
        result_ms = processing.run("native:multiparttosingleparts", params, feedback=feedback)
        ms_part_layer = result_ms['OUTPUT']

        # Execute Drop Z M processing
        params = {'INPUT': ms_part_layer,
                  'DROP_M_VALUES': True,
                  'DROP_Z_VALUES': True,
                  'OUTPUT': 'memory:'}
        result_drop_zm = processing.run("native:dropmzvalues", params, feedback=feedback)
        drop_zm_layer = result_drop_zm['OUTPUT']

        # Extract the QgsFeature from the vector layer
        qgs_in_features = []
        qgs_features = drop_zm_layer.getFeatures()
        for qgs_feature in qgs_features:
            qgs_in_features.append(qgs_feature)
        if len(qgs_in_features) > 1:
            geom_type = qgs_in_features[0].geometry().wkbType()
        else:
            geom_type = drop_zm_layer.wkbType()  # In case of empty layer
        feedback.pushInfo("End normalizing input layer")

        return qgs_in_features, geom_type

    @staticmethod
    def douglas_peucker(qgs_in_features, tolerance, validate_structure=False, feedback=None):
        """Main static method used to launch the simplification of the Douglas-Peucker algorithm.

        :param: qgs_features: List of QgsFeatures to process.
        :param: tolerance: Simplification tolerance in ground unit.
        :param: validate_structure: Validate internal data structure after processing (for debugging only)
        :param: feedback: QgsFeedback handle for interaction with QGIS.
        :return: Statistics and results object.
        :rtype: RbResults
        """

        dp = Simplify(qgs_in_features, tolerance, validate_structure, feedback)
        results = dp.reduce()

        return results

    @staticmethod
    def find_farthest_point(qgs_points, first, last, ):
        """
        Returns a tuple with the farthest point's index and it's distance of a line's section

        Parameters:
            - line: The line to process
            - first: Index of the first point the line's section to test
            - last: Index of the last point the line's section to test

        """

        if last - first >= 2:
            qgs_geom_first_last = QgsLineString(qgs_points[first], qgs_points[last])
            qgs_geom_engine = QgsGeometry.createGeometryEngine(qgs_geom_first_last)
            distances = [qgs_geom_engine.distance(qgs_points[i]) for i in range(first + 1, last)]
            farthest_dist = max(distances)
            farthest_index = distances.index(farthest_dist) + first + 1
        else:
            # Not enough vertice to calculate the farthest distance
            farthest_dist = 0
            farthest_index = first

        return farthest_index, farthest_dist

    __slots__ = ('qgs_in_features', 'tolerance', 'validate_structure', 'feedback', 'rb_collection', 'eps',
                 'rb_results', 'rb_geoms', 'gs_features')

    def __init__(self, qgs_in_features, tolerance, validate_structure, feedback):
        """Constructor for the bend reduction.

       :param: qgs_in_features: List of features to process.
       :param: tolerance: Float tolerance of the diameter of the bend to reduce.
       :param: validate_structure: flag to validate internal data structure after processing (for debugging)
       :param: feedback: QgsFeedback handle for interaction with QGIS.
       """

        self.qgs_in_features = qgs_in_features
        self.tolerance = tolerance
        self.validate_structure = validate_structure
        self.feedback = feedback
        self.eps = None
        self.rb_results = None
        self.gs_features = None
        self.rb_geoms = None
        self.rb_collection = None

    def reduce(self):
        """Main method to reduce line string.

        :return: Statistics and result object.
        :rtype: RbResult
        """

        #  Code used for the profiler (uncomment if needed)
        import cProfile, pstats, io
        from pstats import SortKey
        pr = cProfile.Profile()
        pr.enable()

        # Calculates the epsilon and initialize some stats and results value
        self.eps = Epsilon(self.qgs_in_features)
        self.eps.set_class_variables()
        self.rb_results = RbResults()

        # Create the list of GsPolygon, GsLineString and GsPoint to process
        self.gs_features = GeoSimUtil.create_gs_feature(self.qgs_in_features)
        self.rb_results.in_nbr_features = len(self.qgs_in_features)

        # Pre process the LineString: remove to close point and co-linear points
        self.rb_geoms = self.pre_simplification_process()

        # Create the GsCollection a spatial index to accelerate search
        self.rb_collection = GsCollection()
        self.rb_collection.add_features(self.rb_geoms)

        # Execute the line simplification for each LineString
        self._simplify_lines()

        # Recreate the QgsFeature
        qgs_features_out = [gs_feature.get_qgs_feature() for gs_feature in self.gs_features]

        # Set return values
        self.rb_results.out_nbr_features = len(qgs_features_out)
        self.rb_results.qgs_features_out = qgs_features_out

        # Validate inner spatial structure. For debug purpose only
        if self.rb_results.is_structure_valid:
            self.rb_collection.validate_integrity(self.rb_geoms)

        #  Code used for the profiler (uncomment if needed)

        pr.disable()
        s = io.StringIO()
        sortby = SortKey.CUMULATIVE
        ps = pstats.Stats(pr, stream=s).sort_stats(sortby)
        ps.print_stats()
        print(s.getvalue())


        return self.rb_results

    def pre_simplification_process(self):
        """This method execute the pre simplification process

        Pre simplification process applies only to closed line string and is used to find the 2 points that are
        the distant from each other using the oriented bounding box

        :return: List of rb_geom
        :rtype: [RbGeom]
        """

        # Create the list of RbGeom ==> List of geometry to simplify
        sim_geoms = []
        for gs_feature in self.gs_features:
            sim_geoms += gs_feature.get_rb_geom()

        # Find the 2 most distant vertice in a closed geometry

#        for sim_geom in sim_geoms:
#            qgs_line_string = sim_geom.qgs_geom.constGet()
#            if qgs_line_string.isClosed():
#                qgs_oriented_bbox = sim_geom.qgs_geom.orientedMinimumBoundingBox()
#                qgs_geom_bbox = qgs_oriented_bbox[0]
#                qgs_points_bbox = qgs_geom_bbox.constGet().exteriorRing().points()  # Extract vertice of the bounding box
#                length_axis_0 = qgs_points_bbox[0].distance(qgs_points_bbox[1])
#                length_axis_1 = qgs_points_bbox[1].distance(qgs_points_bbox[2])
#                if length_axis_0 < length_axis_1:
#                    # Find the two shortest sides of the bounding box
#                    qgs_geom_line0 = QgsGeometry(QgsLineString(qgs_points_bbox[0], qgs_points_bbox[1]))
#                    qgs_geom_line1 = QgsGeometry(QgsLineString(qgs_points_bbox[2], qgs_points_bbox[3]))
#                else:
#                    qgs_geom_line0 = QgsGeometry(QgsLineString(qgs_points_bbox[1], qgs_points_bbox[2]))
#                    qgs_geom_line1 = QgsGeometry(QgsLineString(qgs_points_bbox[3], qgs_points_bbox[4]))
#                qgs_points = qgs_line_string.points()
#                distances_line0 = [qgs_geom_line0.distance(QgsGeometry(qgs_point.clone())) for qgs_point in qgs_points]
#                distances_line1 = [qgs_geom_line1.distance(QgsGeometry(qgs_point.clone())) for qgs_point in qgs_points]
#                new_start_end = distances_line0.index(max(distances_line0))


                # Open line string
###                sim_geom.farthest_index = distances_line1.index(max(distances_line1))
###                if new_start_end == sim_geom.farthest_index:
###                    # Special case should not happen but just in case
###                    new_start_end = 0
###                    sim_geom.farthest_index = len(qgs_points)//2
###                if new_start_end != 0:
###                    # Move the first/last vertice to the new location
###                    new_qgs_points = qgs_points[new_start_end:] + qgs_points[1:new_start_end + 1]
###                    sim_geom.qgs_geom = QgsGeometry(QgsLineString(new_qgs_points))

        return sim_geoms

    def _simplify_lines(self):
        """Loop over the geometry until there is no more bend to reduce

        An iterative process for bend reduction is needed in order to maximise the bend reduction.  The process
        will always stabilize and exit when there are no more bends to reduce.

        """

        while True:
            progress_bar_value = 0
            self.rb_results.nbr_pass += 1
            self.feedback.pushInfo("Iteration: {0}".format(self.rb_results.nbr_pass))
            self.feedback.setProgress(progress_bar_value)
            nbr_vertice_deleted = 0
            for i, rb_geom in enumerate(self.rb_geoms):
                if self.feedback.isCanceled():
                    break
                new_progress_bar_value = int(i/len(self.rb_geoms)*100)
                if new_progress_bar_value > progress_bar_value:
                    progress_bar_value = new_progress_bar_value
                    self.feedback.setProgress(progress_bar_value)
                if not rb_geom.is_simplest:  # Only process geometry that are not at simplest form
                    nbr_vertice_deleted += self.process_line(rb_geom)

            self.feedback.pushInfo("Vertice deleted: {0}".format(nbr_vertice_deleted))
            # While loop breaking condition
            if nbr_vertice_deleted == 0:
                break
            self.rb_results.nbr_vertice_deleted += nbr_vertice_deleted

        return

    def validate_constraints(self, sim_geom, first, last):
        """Validate the spatial relationship in order maintain topological structure

        Three distinct spatial relation are tested in order to assure that each bend reduce will continue to maintain
        the topological structure in a feature between the features:
         - Simplicity: Adequate validation is done to make sure that the bend reduction will not cause the feature
                       to cross  itself.
         - Intersection : Adequate validation is done to make sure that a line from other features will not intersect
                          the bend being reduced
         - Sidedness: Adequate validation is done to make sure that a line is not completely contained in the bend.
                      This situation can happen when a ring in a polygon complete;y lie in a bend ans after bend
                      reduction, the the ring falls outside the polygon which make it invalid.

        Note if the topological structure is wrong before the bend correction no correction will be done on these
        errors.

        :param: ind: Index number of the bend to process
        :param: rb_geom: Geometry used to validate constraints
        :param: detect_alternate_bend: Indicates if alternate bend can be find when self intersection is detected
        :return: Flag indicating if the spatial constraints are valid for this bend reduction
        :rtype: Bool
        """

        constraints_valid = True

        # Check if this simplification will create degenerated area (area with 3 points)
        qgs_line_string = sim_geom.qgs_geom.constGet()
        if qgs_line_string.isClosed():
            num_points = qgs_line_string.numPoints()
            if num_points - (last-first-1) <= 3:
                # Not enough point remaining to simplify the line
                return False

        qgs_points = [sim_geom.qgs_geom.vertexAt(i) for i in range(first, last+1)]
        qgs_geom_new_subline = QgsGeometry(QgsLineString(qgs_points[0], qgs_points[-1]))
        qgs_geom_old_subline = QgsGeometry(QgsLineString(qgs_points))
        b_box = qgs_geom_old_subline.boundingBox()
        qgs_geoms_with_itself, qgs_geoms_with_others = \
            self.rb_collection.get_segment_intersect(sim_geom.id, b_box, qgs_geom_old_subline)

        # First: check if the bend reduce line string is an OGC simple line
        # We test with a tiny smaller line to ease the testing and false positive error
        if qgs_geom_new_subline.length() >= Epsilon.ZERO_RELATIVE:
            constraints_valid = GeoSimUtil.validate_simplicity(qgs_geoms_with_itself, qgs_geom_new_subline)
        else:
            # Error in the input file
            x = qgs_points[0].x()
            y = qgs_points[0].y()
            text = "Possibly non OGC simple feature at {},{} use Fix Geometries".format(x, y)
            self.feedback.pushInfo(text)

        # Second: check that the new line does not intersect any other line or points
        if constraints_valid and len(qgs_geoms_with_others) >= 1:
            constraints_valid = GeoSimUtil.validate_intersection(qgs_geoms_with_others, qgs_geom_new_subline)

        # Third: check that inside the bend to reduce there is no feature completely inside it.  This would cause a
        # sidedness or relative position error
        if constraints_valid and len(qgs_geoms_with_others) >= 1:
            qgs_ls_old_subline = QgsLineString(qgs_points)
            qgs_ls_old_subline.addVertex(qgs_points[0])  # Close the line with the start point
            qgs_geom_old_subline = QgsGeometry(qgs_ls_old_subline.clone())
            qgs_geom_unary = QgsGeometry.unaryUnion([qgs_geom_old_subline])  # Create node at each overlap
            qgs_geom_polygonize = QgsGeometry.polygonize([qgs_geom_unary])
            if qgs_geom_polygonize.isSimple():
                constraints_valid = GeoSimUtil.validate_sidedness(qgs_geoms_with_others, qgs_geom_polygonize)
            else:
                print ("polygonize not valid")
                constraints_valid = False

        return constraints_valid

    def process_line(self, sim_geom):
        """
        This method is simplifying a line with the Douglas Peucker algorithm and spatial constraints.

        This method is checking the line differently the first time from the remaining time.  The idea behind
        it is only to have a faster process. We assume that most of the lines will not have a problem so we
        check for problems (SIMPLE_LINE, CROSSING_LINE and SIDEDNESS) against the whole line for the first time.
        If there are some problems the next time we will  check each sub portion of the line.
        This strategy is making a huge difference in time.

        Parameters:
            line: The line to process
            pass_nbr: The number of the pass. At their first pass we process the line as a whole. We do not
            check each sub portion of line simplification. For the other passes we check each sub portion of the line
            for constraints

        Return value:
            True: The line is simplified
            False: The line is not simplified
        """

        stack = []  # Stack to simulate the recursion
        sim_geom.is_simplest = True
        qgs_line_string = sim_geom.qgs_geom.constGet()
        qgs_points = qgs_line_string.points()
        num_points = len(qgs_points)
        last = num_points-1
        if qgs_line_string.isClosed():
            # Initialize stack for a closed line string
            if num_points >= 5:
                mid_index = (num_points // 2)
                stack.append((0, mid_index))
                stack.append((mid_index, num_points-1))
            else:
                # Cannot simplify a line with so few vertice
                pass
        else:
            # Initialize stack for an open line string
            stack.append((0, last))

        nbr_vertice_deleted = 0
        while stack:
            (first, last) = stack.pop()
            if first + 1 < last:  # The segment to check has only 2 points
                (farthest_index, farthest_dist) = Simplify.find_farthest_point(qgs_points, first, last)
                if farthest_dist <= self.tolerance:
                    if self.validate_constraints(sim_geom, first, last):
                        nbr_vertice_deleted += last - first - 1
                        self.rb_collection.delete_vertex(sim_geom, first + 1, last - 1)
                    else:
                        sim_geom.is_simplest = False  # The line string is not at its simplest form
                        # In case of non respect of spatial constraints split and stack again the sub lines
                        (farthest_index, farthest_dist) = Simplify.find_farthest_point(qgs_points, first, last)
                        if farthest_dist <= self.tolerance:
                            stack.append((first, farthest_index))
                            stack.append((farthest_index, last))
                else:
                    stack.append((first, farthest_index))
                    stack.append((farthest_index, last))

        return nbr_vertice_deleted
