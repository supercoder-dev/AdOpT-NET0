import pandas as pd
import numpy as np
import shutil
import os
import json
import requests
from timezonefinder import TimezoneFinder
from pathlib import Path


def load_climate_data_from_api(folder_path, dataset="JRC"):
    """
    Reads in climate data for a full year from a folder containing node data,
    where each node data is stored in a subfolder and node locations are provided in a CSV file named NodeLocations.csv

    :param str folder_path: Path to the folder containing node data and NodeLocations.csv
    :param str dataset: Dataset to import from, can be JRC (only onshore) or ERA5 (global)
    :param int year: Optional, needs to be in range of data available. If nothing is specified, a typical year will be loaded
    :return: None
    """
    # Convert to Path
    if isinstance(folder_path, str):
        folder_path = Path(folder_path)

    # Read NodeLocations.csv with node column as index
    node_locations_path = os.path.join(folder_path, "NodeLocations.csv")
    node_locations_df = pd.read_csv(
        node_locations_path, sep=";", names=["node", "lon", "lat", "alt"]
    )

    # Read nodes and investment_periods from the JSON file
    json_file_path = os.path.join(folder_path, "topology.json")
    with open(json_file_path, "r") as json_file:
        topology = json.load(json_file)

    year = (
        int(topology["start_date"].split("-")[0])
        if topology["start_date"]
        else "typical_year"
    )

    for period in topology["investment_periods"]:
        for node_name in topology["nodes"]:
            # Read lon, lat, and alt for this node name from node_locations_df
            node_data = node_locations_df[node_locations_df["node"] == node_name]
            lon = (
                node_data["lon"].values[0]
                if not pd.isnull(node_data["lon"].values[0])
                else 5.5
            )
            lat = (
                node_data["lat"].values[0]
                if not pd.isnull(node_data["lat"].values[0])
                else 52.5
            )
            alt = (
                node_data["alt"].values[0]
                if not pd.isnull(node_data["alt"].values[0])
                else 10
            )

            if dataset == "JRC":
                # Fetch climate data for the node
                data = import_jrc_climate_data(lon, lat, year, alt)
            else:
                raise Exception("Other APIs are not available")

            # Write data to CSV file
            output_folder = os.path.join(folder_path, period, "node_data", node_name)
            output_file = os.path.join(output_folder, "ClimateData.csv")
            existing_data = pd.read_csv(output_file, sep=";")

            # Fill in existing data with data from the fetched DataFrame based on column names
            for column, value in data["dataframe"].items():
                existing_data[column] = value.values[: len(existing_data)]

            # Save the updated data back to ClimateData.csv
            existing_data.to_csv(output_file, index=False, sep=";")


def fill_carrier_data(
    folder_path, value, columns=None, carriers=None, nodes=None, investment_periods=None
):
    """
    Allows you to easily specify a constant value of Demand, Import limit, Export limit, Import price,
    Export price, Import emission factor, Export emission factor and/or Generic production.

    :param str folder_path: Path to the folder containing the case study data
    :param int value: The new value of the carrier data to be changed
    :param list columns: Name of the columns that need to be changed
    :param list investment_periods: Name of investment periods to be changed
    :param list nodes: Name of the nodes that need to be changed
    :param list carriers: Name of the carriers that need to be changed


    :return: None
    """
    # Convert to Path
    if isinstance(folder_path, str):
        folder_path = Path(folder_path)

    # Reads the topology json file
    json_file_path = folder_path / "topology.json"
    with open(json_file_path, "r") as json_file:
        topology = json.load(json_file)

    # define options
    column_options = [
        "Demand",
        "Import limit",
        "Export limit",
        "Import price",
        "Export price",
        "Import emission factor",
        "Export emission factor",
        "Generic production",
    ]

    for period in (
        investment_periods if investment_periods else topology["investment_periods"]
    ):
        for node_name in nodes if nodes else topology["nodes"]:
            for car in carriers if carriers else topology["carriers"]:

                # Write data to CSV file
                output_folder = (
                    folder_path / period / "node_data" / node_name / "carrier_data"
                )
                filename = car + ".csv"
                output_file = output_folder / filename
                existing_data = pd.read_csv(output_file, sep=";")

                # Fill in existing data with data from the fetched DataFrame based on column names
                for column in columns if columns else column_options:
                    existing_data[column] = value * np.ones(len(existing_data))

                # Save the updated data back to ClimateData.csv
                existing_data.to_csv(output_file, index=False, sep=";")


def copy_technology_data(folder_path, tec_data_path):
    """
    Automatically copies technology JSON files to the node folder for each node and investment period.

    This function reads the topology JSON file to determine the existing and new technologies at each node for
    each investment period. It then searches for the corresponding JSON files in the specified `tec_data_path`
    folder (and its subfolders) using the technology names and copies them to the output folder.

    :param str folder_path: Path to the folder containing the case study data.
    :param str tec_data_path: Path to the folder containing the technology data.
    :return: None
    """
    # Convert to Path
    if isinstance(folder_path, str):
        folder_path = Path(folder_path)
    if isinstance(tec_data_path, str):
        tec_data_path = Path(tec_data_path)

    # Default tec_data_path if not provided
    tec_data_path = tec_data_path / "technology_data"

    # Reads the topology JSON file
    json_file_path = folder_path / "topology.json"
    with open(json_file_path, "r") as json_file:
        topology = json.load(json_file)

    for period in topology["investment_periods"]:
        for node_name in topology["nodes"]:
            # Read the JSON technology file
            json_tec_file_path = (
                folder_path / period / "node_data" / node_name / "Technologies.json"
            )
            with open(json_tec_file_path, "r") as json_tec_file:
                json_tec = json.load(json_tec_file)
            tecs_at_node = json_tec["existing"] + json_tec["new"]

            output_folder = (
                folder_path / period / "node_data" / node_name / "technology_data"
            )
            # Copy JSON files corresponding to technology names to output folder
            for tec_name in tecs_at_node:
                tec_json_file_path = find_json_path(tec_data_path, tec_name)
                if tec_json_file_path:
                    shutil.copy(tec_json_file_path, output_folder)


def copy_network_data(folder_path, ntw_data_path):
    """
    Automatically copies network JSON files to the network_data folder for each investment period.

    This function reads the topology JSON file to determine the existing and new networks for
    each investment period. It then searches for the corresponding JSON files in the specified `ntw_data_path`
    folder (and its subfolders) using the technology names and copies them to the output folder.

    :param str folder_path: Path to the folder containing the case study data.
    :param str ntw_data_path: Path to the folder containing the network data.
    :return: None
    """
    # Convert to Path
    if isinstance(folder_path, str):
        folder_path = Path(folder_path)
    if isinstance(ntw_data_path, str):
        ntw_data_path = Path(ntw_data_path)

    # Default tec_data_path if not provided
    ntw_data_path = ntw_data_path / "network_data"

    # Reads the topology JSON file
    json_file_path = folder_path / "topology.json"
    with open(json_file_path, "r") as json_file:
        topology = json.load(json_file)

    for period in topology["investment_periods"]:
        # Read the JSON network file
        json_ntw_file_path = folder_path / period / "Networks.json"
        with open(json_ntw_file_path, "r") as json_ntw_file:
            json_ntw = json.load(json_ntw_file)
        ntws_at_node = json_ntw["existing"] + json_ntw["new"]

        output_folder = folder_path / period / "network_data"
        # Copy JSON files corresponding to technology names to output folder
        for ntw_name in ntws_at_node:
            ntw_json_file_path = find_json_path(ntw_data_path, ntw_name)
            if ntw_json_file_path:
                shutil.copy(ntw_json_file_path, output_folder)


def find_json_path(data_path, name):
    """
    Search for a JSON file with the given technology name in the specified path and its subfolders.

    :param str data_path: Path to the folder containing technology JSON files.
    :param str name: Name of the technology.
    :return: Path to the JSON file if found, otherwise None.
    """
    for root, dirs, files in os.walk(data_path):
        for file in files:
            if file.lower() == f"{name.lower()}.json":
                return Path(root) / Path(file)


def import_jrc_climate_data(lon, lat, year, alt):
    """
    Reads in climate data for a full year from `JRC PVGIS <https://re.jrc.ec.europa.eu/pvg_tools/en/>`_.

    The returned dataframe is consistent with the energyhub format requirements.

    :param float lon: longitude of node - the api will read data for this location
    :param float lat: latitude of node - the api will read data for this location
    :param int year: optional, needs to be in range of data available. If nothing is specified, a typical year \
    will be loaded
    :param float alt: altitude of location specified
    :return: dict containing information on the location (altitude, longitude, latitude and a dataframe \
    containing climate data (ghi = global horizontal irradiance, dni = direct normal irradiance, \
    dhi = diffuse horizontal irradiance, rh = relative humidity, temp_air = air temperature, ws = wind speed at \
    specified hight. Wind speed is returned as a dict for different heights.
    """
    # get time zone
    tf = TimezoneFinder()
    tz = tf.timezone_at(lng=lon, lat=lat)

    # Specify year import, lon, lat
    if year == "typical_year":
        parameters = {"lon": lon, "lat": lat, "outputformat": "json"}
        time_index = pd.date_range(start="2001-01-01 00:00", freq="1h", periods=8760)
    else:
        parameters = {"lon": lon, "lat": lat, "year": year, "outputformat": "json"}
        time_index = pd.date_range(
            start=str(year) + "-01-01 00:00", end=str(year) + "-12-31 23:00", freq="1h"
        )

    # Get data from JRC dataset
    answer = dict()
    print("Importing Climate Data...")
    response = requests.get("https://re.jrc.ec.europa.eu/api/tmy?", params=parameters)
    if response.status_code == 200:
        print("Importing Climate Data successful")
    else:
        print(response)
    data = response.json()
    climate_data = data["outputs"]["tmy_hourly"]

    # Compile return dict
    answer["longitude"] = lon
    answer["latitude"] = lat
    answer["altitude"] = alt

    ghi = []
    dni = []
    dhi = []
    rh = []
    temp_air = []
    wind_speed = dict()
    wind_speed["10"] = []

    for t_interval in climate_data:
        ghi.append(t_interval["G(h)"])
        dni.append(t_interval["Gb(n)"])
        dhi.append(t_interval["Gd(h)"])
        rh.append(t_interval["RH"])
        temp_air.append(t_interval["T2m"])
        wind_speed["10"].append(t_interval["WS10m"])

    answer["dataframe"] = pd.DataFrame(
        np.array([ghi, dni, dhi, temp_air, rh]).T,
        columns=["ghi", "dni", "dhi", "temp_air", "rh"],
        index=time_index,
    )
    for ws in wind_speed:
        answer["dataframe"]["ws" + str(ws)] = wind_speed[ws]

    return answer