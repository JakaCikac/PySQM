#!/usr/bin/env python

"""
PySQM main program
____________________________

Copyright (c) Mireia Nievas <mnievas[at]ucm[dot]es>

This file is part of PySQM.

PySQM is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

PySQM is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with PySQM.  If not, see <http://www.gnu.org/licenses/>.
____________________________
"""

import os
import sys
import time
import datetime
import argparse

import pysqm.settings as settings
from pysqm.read import *
import pysqm.plot

# Read input arguments (if any)
parser = argparse.ArgumentParser(description="SQM Measurement Recorder")
parser.add_argument("-c", "--config", help="Path to the configuration file", default="config.py")
parser.add_argument("-i", "--input_file", help="Input File", default=None)
args = parser.parse_args()
config_filename = args.config

# Load config contents into GlobalConfig
settings.GlobalConfig.read_config_file(config_filename)

# Get the actual config
config = settings.GlobalConfig.config

'''
This import section is only for software build purposes.
Dont worry if some of these are missing in your setup.
'''


def relaxed_import(themodule):
    try:
        exec ('import ' + str(themodule))
    except:
        pass


relaxed_import('socket')
relaxed_import('serial')
relaxed_import('_mysql')
relaxed_import('pysqm.email')

'''
Conditional imports
'''

# If the old format (SQM_LE/SQM_LU) is used, replace _ with -
config.device_type = config.device_type.replace('_', '-')

if config.device_type == 'SQM-LE':
    import socket
elif config.device_type == 'SQM-LU':
    import serial
if config._use_mysql == True:
    import _mysql

# Create directories if needed
for directory in [config.monthly_data_directory, config.daily_data_directory, config.current_data_directory]:
    if not os.path.exists(directory):
        os.makedirs(directory)

'''
Select the device to be used based on user input
and start the measures
'''

if config.device_type == 'SQM-LU':
    my_device = SQMLU()
elif config.device_type == 'SQM-LE':
    my_device = SQMLE()
else:
    print('ERROR. Unknown device type ' + str(config.device_type))
    exit(0)


def loop():
    """
    Ephem is used to calculate moon position (if above horizon)
    and to determine start-end times of the measures
    """
    observ = define_ephem_observatory()
    niter = 0
    daytime_print = True
    print('Starting readings ...')
    while 1 < 2:
        ''' The programs works as a daemon '''
        utcdt = my_device.read_datetime()
        # print (str(mydevice.local_datetime(utcdt))),
        if my_device.is_nighttime(observ):
            # If we are in a new night, create the new file.
            config._send_to_datacenter = False  ### Not enabled by default
            try:
                assert (config._send_to_datacenter == True)
                assert (niter == 0)
                my_device.save_data_datacenter("NEWFILE")
            except:
                pass

            start_date_time = datetime.datetime.now()
            niter += 1

            my_device.define_filenames()

            ''' Get values from the photometer '''
            try:
                timeutc_mean, timelocal_mean, temp_sensor, \
                freq_sensor, ticks_uC, sky_brightness = \
                    my_device.read_photometer( \
                        Nmeasures=config._measures_to_promediate, PauseMeasures=10)
            except:
                print('Connection lost')
                if config._reboot_on_connlost == True:
                    sleep(600)
                    os.system('reboot.bat')

                time.sleep(1)
                my_device.reset_device()

            formatted_data = my_device.format_content( \
                timeutc_mean, timelocal_mean, temp_sensor, \
                freq_sensor, ticks_uC, sky_brightness)

            try:
                assert (config._use_mysql == True)
                my_device.save_data_mysql(formatted_data)
            except:
                pass

            try:
                assert (config.send_to_datacenter == True)
                my_device.save_data_datacenter(formatted_data)
            except:
                pass

            my_device.data_cache(formatted_data, number_measures=config.cache_measures, niter=niter)

            if niter % config.plot_each == 0:
                ''' Each X minutes, plot a new graph '''
                try:
                    pysqm.plot.make_plot(send_emails=False, write_stats=False)
                except:
                    print('Warning: Error plotting data.')
                    print(sys.exc_info())

            if not daytime_print:
                daytime_print = True

            main_delta_seconds = (datetime.datetime.now() - start_date_time).total_seconds()
            time.sleep(max(1, config.delay_between_measures - main_delta_seconds))

        else:
            ''' Daytime, print info '''
            if daytime_print:
                utcdt = utcdt.strftime("%Y-%m-%d %H:%M:%S")
                print (utcdt),
                print('. Daytime. Waiting until ' + str(my_device.next_sunset(observ)))
                daytime_print = False
            if niter > 0:
                my_device.flush_cache()
                if config.send_data_by_email:
                    try:
                        pysqm.plot.make_plot(send_emails=True, write_stats=True)
                    except:
                        print('Warning: Error plotting data / sending email.')
                        print(sys.exc_info())

                else:
                    try:
                        pysqm.plot.make_plot(send_emails=False, write_stats=True)
                    except:
                        print('Warning: Error plotting data.')
                        print(sys.exc_info())

                niter = 0

            # Send data that is still in the data center buffer
            try:
                assert config.send_to_datacenter is True
                my_device.save_data_datacenter("")
            except AssertionError:
                pass

            time.sleep(300)
