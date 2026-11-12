---
title: About the data
section: Getting started
order: 15
keywords: data, sensor, photodiode, meltview, laserview, plasma, melt pool, meltpool, wavelength, sampling, 100 khz, packet, dat, raw, mean, median, columns, units, start time, duration, demand, back reflection, output power, noise, signal
---
# About the data

Where the numbers come from, what was done to them before they reached the
app, and what each column means.

## How the build is monitored

The monitoring sensors are photodiodes that look down the **same optical path
as the laser**. They follow the laser across the plate and always see the spot
it is working on: a viewing area about **5 mm in diameter**.

Every sensor is sampled at **100 kHz**, one reading every 10 microseconds.

Two photodiodes watch the light given off by the process, each in its own
band of wavelengths:

| Signal | Wavelengths | Watches |
| --- | --- | --- |
| **MeltVIEW plasma** | 700 nm to 1040 nm | The plasma above the melt pool. |
| **MeltVIEW melt pool** | 1090 nm to 1700 nm | The infrared glow of the melt pool itself. |

## From raw data to packet data

The machine records the raw readings in DAT files. The app does not read
those. It reads **packet data**, which is the raw data after processing:

- **Non-processing data is removed.** Transients and the readings taken while
  the laser was not processing are dropped.
- **Readings are averaged over time for each point.** Every point the laser
  passes through gets a single value for each photodiode.
- **There is one file per layer.**

At 100 kHz a point holds several raw readings. A point the laser dwells on for
50 microseconds, for example, holds five.

### Mean and median

Because each value stands for several readings, the packet data gives every
signal twice: as the **mean** and as the **median** of the readings at that
point. That is why the column list has pairs such as
*MeltVIEW melt pool (mean)* and *MeltVIEW melt pool (median)*.

The mean uses every reading. The median is the middle reading, so one stray
spike within a point moves it less. The mean columns are the ones loaded by
default; tick the median ones on the
[DataStore setup](help:datastore-setup) page if you want them.

## Which signal to use

- **Melt pool** is typically the most useful signal, because it indicates the
  thermal response of the material.
- Melt pool is a much **noisier** signal than plasma.
- **Plasma** is cleaner, but it tends to max out easily and plateau. Once it
  has plateaued it no longer tells conditions apart.

## The columns

Each row is one point. The names below are the ones in the packet data; the
second column is the shorter name a new build gives them by default.

### Where and when

| Column | Default name | Meaning |
| --- | --- | --- |
| **Start time** | | When the laser reached the point, in microseconds from the start of the layer. No two points of a layer share a start time. |
| **Duration** | | How long the laser stayed on the point, in microseconds. |
| **Demand X**, **Demand Y** | *X*, *Y* | Where the laser was sent: the commanded position on the plate, in mm. |
| **Demand focus** | | The commanded focus offset. |

### The process signals

| Column | Default name | Meaning |
| --- | --- | --- |
| **MeltVIEW melt pool** | *Meltpool* | The melt pool photodiode (1090 nm to 1700 nm). |
| **MeltVIEW plasma** | *Plasma* | The plasma photodiode (700 nm to 1040 nm). |

### The laser

| Column | Default name | Meaning |
| --- | --- | --- |
| **Demand laser power** | *Demand Power* | The power the laser was asked for. |
| **Laser output power** | *Output power* | The power the laser reports it delivered. |
| **LaserVIEW** | | A photodiode on the laser light itself, measured in the optical path. The [melt-pool correction](help:datastore-setup) uses it as its reference, which is why it always loads. |
| **Laser back reflection** | | Laser light reflected back up the optical path. |

Every column in the last two tables comes as a *(mean)* and a *(median)*.

### Added by the app

| Column | Meaning |
| --- | --- |
| **layer** | The layer the point belongs to, taken from its file. |
| **Z** | The height of the layer: the layer number times the layer thickness. |
| **part_id** | The part the point belongs to, when the build has a [part assignment](help:parts). |

## Reading the values

The signal values are sensor readings in the sensors' own units. They are not
temperatures, and the laser columns are not watts. Use them to compare: one
part against another, one layer against the next, one parameter set against
another.

## See also

- [Setting up the DataStore](help:datastore-setup): choosing and renaming the
  columns to load.
- [The Data tab](help:data-tab)
- [CoV summary](help:plot-cov): measuring how steady a signal is.
