<?xml version="1.0"?>
<launch>
  <!--ROS2 Launch file with intentional issues-->

  <!-- Bug: Hardcoded parameters, no parameter file, missing remappings -->
  <node pkg="my_package" exec="publisher_node" name="publisher">
    <!-- Missing namespace declaration -->
    <!-- Hardcoded topic names - should be remappable -->
    <remap from="topic" to="chatter"/>  <!-- Good: has remap -->
    <!-- Missing remap for other topics -->
    <!-- No parameter declarations -->
  </node>

  <!-- Bug: Another node with incomplete configuration -->
  <node pkg="my_package" exec="subscriber_node" name="subscriber">
    <!-- Missing remap altogether -->
    <!-- No parameters -->
    <!-- Potential issue: no output configuration -->
  </node>

  <!-- Bug: Group without proper include -->
  <!-- Missing include for common launch files -->

</launch>
