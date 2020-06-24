# Fusion 360 Gallery Dataset

The *Fusion 360 Gallery Dataset* contains rich 2D and 3D geometry data derived from parametric CAD models. The dataset is produced from designs submitted by users of the CAD package [Autodesk Fusion 360](https://www.autodesk.com/products/fusion-360/overview) to the [Autodesk Online Gallery](https://gallery.autodesk.com/fusion360). The dataset provides valuable data for learning how people design, including sequential CAD design data, designs segmented by modeling operation, engineering sketches with dimensions and constraints, and design hierarchy and connectivity data.

![Fusion 360 Gallery Dataset](docs/images/fusion_gallery_mosaic.jpg)


## Data Subsets
From the approximately 20,000 designs available we derive several data 'subsets' focused on specific areas of research. Currently the following data subsets are available to download, with more to be released on an ongoing basis.

- [Segmentation Subset](docs/segmentation.md): A segmentation of design bodies based on the modeling operation used to create each face, e.g. Extrude, Fillet, Chamfer etc...
-  [Reconstruction Subset](docs/reconstruction.md): Sequential design data from a subset of simple 'sketch and extrude' components that enables final geometry to be reconstructed.


## Download
The following data subsets are available to download:

| Data Subset | Download |
| - | - |
| [Segmentation](docs/segmentation.md) | [Version d5](https://github.com/karldd/Fusion360GalleryDataset/releases/tag/d5) |
| [Reconstruction](docs/reconstruction.md) | [Version d4](https://github.com/karldd/Fusion360GalleryDataset/releases/tag/d4) |


## Documentation
Documentation of the dataset is ongoing and will include details of the formats used in the dataset and statistics about the dataset as a whole. Documentation can be found in the [docs directory](docs).

## Tools
As part of the dataset we provide various tools for working with the data. These tools leverage the [Fusion 360 API](http://help.autodesk.com/view/fusion360/ENU/?guid=GUID-7B5A90C8-E94C-48DA-B16B-430729B734DC) to perform operations such as geometry reconstruction, traversing B-Rep data structures, and conversion to other formats. More information can be found in the [tools directory](tools).

## License
The dataset to which this license is attached is trial data from the Autodesk Fusion 360 Dataset (the "Trial Dataset") provided by Autodesk, Inc. Its use is subject to the following terms and conditions:
1.	You shall use the Trial Dataset only for non-commercial research and educational purposes.
2.	You shall not redistribute the Trial Dataset outside your organization. You may share the Trial Dataset with other research teams within your organization provided that that a representative of such team first agrees to be bound by these terms and conditions.
3.	Autodesk makes no representations or warranties regarding the Trial Dataset, including but not limited to warranties of non-infringement or fitness for a particular purpose.
4.	You accept full responsibility for your use of the Trial Dataset and shall defend and indemnify Autodesk, Inc. including its employees, officers and agents, against any and all claims arising from your use of the Trial Dataset, including but not limited to your use of any copies of copyrighted images that he or she may create from the Trial Dataset.
5.	Autodesk reserves the right to terminate this license at any time.
6.	These terms and conditions shall apply to your use of any future release of the Trial Dataset unless Autodesk publishes the Trial Dataset with a publicly-facing license to the Trial Dataset with terms that are less restrictive on you, in which case such less restrictive terms shall apply to you. Provided for clarity that this license shall not be applicable to the anticipated non-trial version of the Fusion 360 Dataset.
7.	The laws of the State of California shall apply to all disputes under this agreement.

## Publications
As we publish the data we benchmark tasks we will provide a list of research papers and citations here.