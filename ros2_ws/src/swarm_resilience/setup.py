from setuptools import find_packages, setup

package_name = "swarm_resilience"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Mohammed Kaish Ansari",
    maintainer_email="iiitu.kaish@gmail.com",
    description="Swarm resilience prototype",
    license="MIT",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "drone_agent = swarm_resilience.drone_agent:main",
            "operator_node = swarm_resilience.operator_node:main",
            "swarm_monitor = swarm_resilience.swarm_monitor:main",
        ],
    },
)
