import distutils.cmd
import distutils.log
import os
import subprocess

# mypy: ignore-errors
from setuptools import find_packages, setup


class MypyCmd(distutils.cmd.Command):
    """Custom command to run Mypy"""

    description = "run Mypy on kentik_api directory"
    user_options = [("packages=", None, "Packages to check with mypy")]

    def initialize_options(self):
        """Set default values for options"""
        # noinspection PyAttributeOutsideInit
        self.packages = ["."]

    def finalize_options(self):
        """Post-process options."""
        for package in self.packages:
            assert os.path.exists(package), "Path {} does not exist.".format(package)

    def run(self):
        """Run command"""
        cmd = ["mypy"]
        for package in self.packages:
            cmd.append(package)
        self.announce("Run command: {}".format(str(cmd)), level=distutils.log.INFO)
        try:
            subprocess.check_call(cmd)
        except subprocess.CalledProcessError:
            self.announce(
                "Command: {} returned error. Check if tests are not failing.".format(str(cmd)),
                level=distutils.log.INFO,
            )


setup(
    name="kentik-image-cache",
    use_scm_version={
        "root": ".",
        "relative_to": __file__,
    },
    description="Cache for Kentik API produced images",
    long_description="Application for caching of images rendered by the _/query/topxchart_ Kentik API method.",
    url="https://github.com/kentik/kentik_image_cache",
    license="Apache-2.0",
    install_requires=["fastapi>=0.65.1", "kentik-api>=0.2.0"],
    setup_requires=["pytest-runner", "setuptools_scm"],
    tests_require=["httpretty", "pytest", "mypy", "typer"],
    packages=find_packages(),
    cmdclass={"mypy": MypyCmd},
    classifiers=[
        "License :: OSI Approved :: Apache Software License",
    ],
)
