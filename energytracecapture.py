import xml.etree.ElementTree as ET
import lz4.frame
import numpy as np
import concurrent.futures
import os

class EnergyTraceCapture:
    # To know which record we are looking at
    index = 0
    # EnergyTrace capture name
    name = ""
    _energy = 0
    _current = 0
    _timestamp = 0
    max_current_value = 0
    min_current_value = 0
    max_energy_value = 0
    min_energy_value = 0
    # Keep a save of the length, so that we do not have to recount everytime
    length = 0
    voltage = 0

    def __init__(self, filename):
        current_array = np.array([], dtype=np.uint32)
        energy_array = np.array([], dtype=np.uint32)
        timestamps_array = np.array([], dtype=np.uint32)
        
        # Check what type of file we want to parse
        if filename.find(".csv") != -1:
            # Get first file
            name, current_array, energy_array, timestamps_array = self._parse_csv(filename)
            # Now check if there are any other files we should parse and append to our arrays
            i = 0
            # TODO: Paralellize operation in the future
            while True:
                next_csv = filename.replace(".csv", "_" + str(i) + ".csv")
                if os.path.exists(next_csv):
                    name, current, energy, timestamps = self._parse_csv(next_csv)
                    current_array = np.append(current_array, current)
                    energy_array = np.append(energy_array, energy)
                    timestamps_array = np.append(timestamps_array, timestamps)
                else:
                    break
                i += 1

        else:
            self._type = "profxml"
            # Assume .profxml, and load the root XML file
            infotree = ET.parse(filename)

            # Get the root element
            root = infotree.getroot()

            # Now give XML metadata path to parse all binaries
            bin_filefolder = filename.replace('.profxml', '') +'/ETData.xml'

            # Load the metadata XML file...
            bintree = ET.parse(bin_filefolder).getroot()
            # ...and extract the binary file names
            bindata_filenames = []
            bindata_lengths = []
            for elem in bintree.iter():
                if elem.get('class') == "com.ti.dvt.uia.utils.MultipleBinaryDataFile$BinaryDataFile":
                    for subelem in elem.iter():
                        # Filename
                        if subelem.get('property') == "filename":
                            bindata_filenames.append(bin_filefolder.replace("ETData.xml", subelem[0].text))
                        # Length of the binary file
                        if subelem.get('property') == "length":
                            bindata_lengths.append(int(subelem[0].text))
            
            # Not really necessary due to GIL
            with concurrent.futures.ThreadPoolExecutor() as executor:
                results = list(executor.map(self.__parse_bin, bindata_filenames, bindata_lengths))

            for result in results:
                name, current, energy, timestamp = result
                current_array = np.append(current_array, current)
                energy_array = np.append(energy_array, energy)
                timestamps_array = np.append(timestamps_array, timestamp)
            
        self.length = timestamps_array.size
        self.max_current_value = np.amax(current_array)
        self.min_current_value = np.amin(current_array)
        self.max_energy_value = np.amax(energy_array)
        self.min_energy_value = np.amin(energy_array)

        # Could use better checking
        self._type = current_array.dtype
        self._current = lz4.frame.compress(current_array.tobytes())
        self._energy = lz4.frame.compress(energy_array.tobytes())
        self._timestamp = lz4.frame.compress(timestamps_array.tobytes())

        self.name = filename
    
    # TODO: Create a fail case with a return value
    def __parse_bin(self, filename, length):
        current = np.array(length)
        energy = np.array(length)
        timestamp = np.array(length)

        content = np.fromfile(filename, dtype=np.uint8)
        
        # Find correct offset
        offset = np.where(content == 0x08)[0][0]
        if (offset != 0):
            content = content[offset:]

        # Check for padding needed
        if len(content) % 18 != 0:
            padding = 18 - (len(content) % 18)
            content = np.pad(content, (0, padding), "edge")

        content = np.reshape(content, (-1, 18))

        dt = np.dtype(np.uint32)
        dt = dt.newbyteorder('<')

        current = np.frombuffer(content[:,8:12].flatten(), dtype=dt)
        timestamp = np.frombuffer(content[:,1:5].flatten(), dtype=dt)
        energy = np.frombuffer(content[:,14:18].flatten(), dtype=dt)

        return filename, current, energy, timestamp
    
    def _parse_csv(self, filename):
        # Assume Time(ms),Current(nA),Energy(uJ) layout
        timestamp, current, energy = np.genfromtxt(filename, names=True, delimiter=",",  usecols = (0,2,3), unpack=True)

        return filename, current, energy, timestamp * 1000
            
    @property
    def current(self):
        return np.frombuffer(lz4.frame.decompress(self._current), self._type)
    
    @property
    def energy(self):
        return np.frombuffer(lz4.frame.decompress(self._energy), self._type)
    
    @property
    def timestamp(self):
        return np.frombuffer(lz4.frame.decompress(self._timestamp), self._type)
            

