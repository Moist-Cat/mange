import setuptools
from pathlib import Path

with open("README.md", "r") as file:
    long_description = fh.read()

with open("requirements.txt") as file:
    REQUIREMENTS = file.read().split("\n")

setuptools.setup(
     name="mange",
     version="1.0.0",
     long_description=long_description,
   long_description_content_type="text/markdown",
     scripts=["mange"],
     install_requires=REQUIREMENTS,
     include_package_data=True,
     package_dir={"":"src"},
     packages=setuptools.find_packages(where="src"),
     python_requires=">=3.8",
     classifiers=[
         "Programming Language :: Python :: 3",
         "License :: OSI Approved :: MIT License",
         "Operating System :: Linux",
     ],
 )
