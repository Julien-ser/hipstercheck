#!/usr/bin/env python3
"""
ROS2 Publisher Node with intentional issues for testing.
Issues: missing type hints, bare except, no error handling, uninitialized variables
"""

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
import time


# Missing type hints
def create_publisher(node):
    return node.create_publisher(String, "topic", 10)


# Uninitialized variable issue
def process_data(data):
    # result not initialized before use in some paths
    if len(data) > 5:
        result = "long"
    # Missing else branch - potential uninitialized use
    return result  # Bug: result might be undefined


class MyNode(Node):
    def __init__(self):
        # Missing call to super().__init__() with proper name
        super().__init__("my_node")  # Good: this is correct
        self.publisher = create_publisher(self)
        self.timer = self.create_timer(1.0, self.timer_callback)
        self.count = 0

    def timer_callback(self):
        msg = String()
        msg.data = f"Count: {self.count}"
        self.publisher.publish(msg)
        self.count += 1


# Bare except clause - bad practice
def risky_function():
    try:
        # Some operation that might fail
        import nonexistent_module
    except:  # Bug: bare except catches everything
        print("Something went wrong")
        # No proper error handling or re-raising


# Missing type hints throughout
def another_function(x, y):
    z = x + y
    return z


if __name__ == "__main__":
    rclpy.init()
    node = MyNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
