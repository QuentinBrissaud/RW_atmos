#!/usr/bin/env python3
import numpy as np
import os
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
from pdb import set_trace as bp
from pyrocko import moment_tensor as mtm
from obspy.core.utcdatetime import UTCDateTime
from obspy.geodetics.base import gps2dist_azimuth, degrees2kilometers, kilometer2degrees
from pyrocko.moment_tensor import rotation_from_angle_and_axis
from obspy.clients.fdsn import Client
import sys

## display parameters
font = {'size': 14}
matplotlib.rc('font', **font)

## To make sure that there is no bug when saving and closing the figures
## https://stackoverflow.com/questions/27147300/matplotlib-tcl-asyncdelete-async-handler-deleted-by-the-wrong-thread
matplotlib.use('Agg')

def transform_domain_power2(xmin_in, xmax_in, dx):
        
    def nextpow2(x):
            return np.ceil(np.log2(abs(x)))

    xmax = xmax_in
    xmin = xmin_in
    NFFT  = int(abs(xmax-xmin)/dx)
    
    NFFT_  = 0
    factor = 0
    while NFFT > NFFT_:
            #xlength_ = 2**(nextpow2(xlength) + factor)
            NFFT_   = 2**(nextpow2(NFFT) + factor)
            factor += 1
    
    dx_   = dx
    xmax_ = NFFT_ * dx_ + xmin
    diff  = xmax_ - xmax
    xmin_ = xmin - diff/2
    xmax_ = xmax + diff/2
    
    factor_divide = 1.2
    while xmax_ > xmax:
    
            dx_   /= factor_divide
    
            xmax_  = NFFT_ * dx_ + xmin
            diff   = xmax_ - xmax
            xmin_ = xmin - diff/2
            xmax_ = xmax + diff/2
            #print(dx_, xmin_, xmax_)
    
    if not dx_ == dx:
            dx_   *= factor_divide

    xmax_  = NFFT_ * dx_ + xmin
    diff   = xmax_ - xmax
    xmin_ = xmin - diff/2
    xmax_ = xmax + diff/2
    
    return xmin_, xmax_, dx_    

def get_domain(lat_source, lon_source, lat_max_in_, lat_min_in_, lon_max_in_, lon_min_in_, dimension, dchosen = 50):
        
    lat_max_in = lat_max_in_
    lat_min_in = lat_min_in_
    if(abs(lat_min_in-lat_max_in) < 1e-3):
            lat_min_in -= 0.1
    lon_max_in = lon_max_in_
    lon_min_in = lon_min_in_
    if(abs(lon_min_in-lon_max_in) < 1e-3):
            lon_min_in -= 0.1
    
    factor = 0
    dshift = 15000.
    #dchosen = 80
    
    diff = abs(lat_max_in_ - lat_min_in_)
    if diff < 0.25:
            lat_max_in = lat_max_in_ + diff/2.
            lat_min_in = lat_min_in_ - diff/2.
            
    diff = abs(lon_max_in_ - lon_min_in_)
    if diff < 0.25:
            lon_max_in = lon_max_in_ + diff/2.
            lon_min_in = lon_min_in_ - diff/2.
            
    dlon, dlat = abs(lon_max_in-lon_min_in)/dchosen, abs(lat_max_in-lat_min_in)/dchosen

    lat_max, lat_min = degrees2kilometers(lat_max_in)*1000., degrees2kilometers(lat_min_in)*1000.
    lon_max, lon_min = degrees2kilometers(lon_max_in)*1000., degrees2kilometers(lon_min_in)*1000.

    dx, dy, dz = abs(lon_max-lon_min)/dchosen, abs(lat_max-lat_min)/dchosen, 200.

    xmin, xmax = lon_min - factor*dy - dshift, lon_max + factor*dy + dshift
    ymin, ymax = lat_min - factor*dx - dshift, lat_max + factor*dx + dshift
    zmax = 30000.
    
    ## Transform domain to make x and y powers of two
    xmin_, xmax_, dx_ = transform_domain_power2(xmin, xmax, dx)
    #ymin_, ymax_, dy_ = transform_domain_power2(ymin, ymax, dy)
    xmin, xmax, dx = xmin_, xmax_, dx_
    #ymin, ymax, dy = ymin_, ymax_, dy_
    #int(2**nextpow2((xmax-xmin)/dx))
    
    if dimension == 3:
    
            if abs(dy) < 1e-5:
                    dy = (ymax-ymin)/10 ## DEFAULT VALUE
            
            
            ymin_, ymax_, dy_ = transform_domain_power2(ymin, ymax, dy)
            ymin, ymax, dy = ymin_, ymax_, dy_
    
            yy   = np.arange(ymin, ymax, dy)
            ymin = yy[0]
            ymax = yy[-1]
            loc_ = np.argmin(abs(yy))
            if abs(yy[loc_]) < 1e-5:
                    ymax -= yy[loc_]
                    ymin -= yy[loc_]
    
    ## OLD before Jul 13 2020
    dx, dy = abs(xmax-xmin)/dchosen, abs(ymax-ymin)/dchosen
    
    domain = {}
    domain.update( {'origin': (lat_source, lon_source)} )
    domain.update( {'latmin': lat_source + kilometer2degrees(ymin/1000.), 'latmax': lat_source + kilometer2degrees(ymax/1000.)} )
    domain.update( {'lonmin': lon_source + kilometer2degrees(xmin/1000.), 'lonmax': lon_source + kilometer2degrees(xmax/1000.)} )
    domain.update( {'xmin': xmin, 'xmax': xmax} )
    domain.update( {'ymin': ymin, 'ymax': ymax} )
    domain.update( {'zmin': 0., 'zmax': zmax} )
    domain.update( {'dx': dx, 'dy': dy, 'dz': dz} )
    
    return domain

def compute_coordinate_USE(distances):

    dist = distances[0]
    azi  = distances[1]*np.pi/180.
    x = np.sin(azi) * dist
    y = np.cos(azi) * dist
    
    return x, y

def add_source_parameters(x, options_source, dimension, data_GPS=pd.DataFrame()):

    print('Loading source and stations for event ' + str(x['EVID']))

    x['stf']      = options_source['stf'] # gaussian or erf
    x['stf-data'] = options_source['stf-data'] # gaussian or erf
    x['zsource'] = x['DEPTH']*1000.
    x['f0']      = options_source['f0'] # 0.4
    x['M0']      = 1e0
    type_mag     = x['M']
    
    mw = x['MAG'] if type_mag == 'w' else (2./3.)*x['MAG'] + 1.15
    m0 = mtm.magnitude_to_moment(mw)  # convert the mag to moment
    strike, dip, rake = x['STRIKE'], x['DIP'], x['RAKE']
    mt = mtm.MomentTensor(strike=strike, dip=dip, rake=rake, scalar_moment=m0)
    
    x['startdate'] = UTCDateTime(x['#YYY/MM/DD'].replace('/','-') + 'T' + x['HH:mm:SS.ss'])
    
    #x['balloon'] = {}
    x['balloons'] = {}
    any_balloon = False
    lat_max, lat_min = -190, 190
    lon_max, lon_min = -190, 190
    if data_GPS.size > 0:
        for name_balloon in data_GPS['name'].unique():
    
            sub_df = data_GPS.loc[ data_GPS['name'] == name_balloon, : ]
    
            balloon = True
            if(sub_df['startdate'].iloc[0]>x['startdate'] or sub_df['startdate'].iloc[-1]<x['startdate']):
                    balloon = False
            
            #x['balloon'].update( {name_balloon: balloon} )
            
            if(not balloon):
                    continue
    
            any_balloon = True
            loc_time = np.argmin(abs(sub_df['startdate']-x['startdate']).values)
            x['balloons'].update( {name_balloon: {'azimuth':gps2dist_azimuth(x['LAT'], x['LON'], sub_df.iloc[loc_time]['Lat'], sub_df.iloc[loc_time]['Lon']), 'balloon': sub_df.iloc[loc_time] }} )
            
            if(options_source['rotation']):
                    if name_balloon == options_source['rotation-towards']:
                            #lat_max = (sub_df.iloc[loc_time]['Lat'] - x['LAT'])
                            #lat_min = (sub_df.iloc[loc_time]['Lat'] - x['LAT'])
                            londiff, latdiff = (sub_df.iloc[loc_time]['Lon'] - x['LON']), (sub_df.iloc[loc_time]['Lat'] - x['LAT'])
                            lon_max = max( lon_max, np.sqrt(londiff**2 + latdiff**2) )
                            lon_min = min( lon_min, np.sqrt(londiff**2 + latdiff**2) )
            else:
                    lat_max = max( lat_max, (sub_df.iloc[loc_time]['Lat'] - x['LAT']) )
                    lat_min = min( lat_min, (sub_df.iloc[loc_time]['Lat'] - x['LAT']) )
                    lon_max = max( lon_max, (sub_df.iloc[loc_time]['Lon'] - x['LON']) )
                    lon_min = min( lon_min, (sub_df.iloc[loc_time]['Lon'] - x['LON']) )

    x['any_balloon'] = any_balloon
    x['station_tab'] = {}
    x['M']   = []
    x['phi'] = 0.
    ## Create balloon stations
    if(any_balloon):
    
            keys = [ikey for ikey in x['balloons'].keys()]
            azimuth_balloon = x['balloons'][keys[0]]['azimuth'][1]
            if(options_source['rotation']):
                    key_balloon = options_source['rotation-towards']
                    azimuth_balloon = x['balloons'][key_balloon]['azimuth'][1]
                    mt = mt.rotated(rotation_from_angle_and_axis(90-azimuth_balloon, [0,0,1])  )
            
            if options_source['activate_LA']:
                    x['LAT'], x['LON'] = 34.066, -119.3983
            
            id_in = 0
            if(options_source['rotation']):
                    stat_loc, id_in  = create_stations(x['balloons'][key_balloon]['azimuth'][0], 0., x['balloons'][key_balloon]['balloon']['Alt'], key_balloon, id_in, t_chosen = options_source['t_chosen'], balloon=True)
            else:
                    x_, y_ = compute_coordinate_USE(x['balloons'][keys[0]]['azimuth'])
                    stat_loc, id_in  = create_stations(x_, y_, x['balloons'][keys[0]]['balloon']['Alt'], keys[0], id_in, t_chosen = options_source['t_chosen'], balloon=True)
                    
            x['station_tab'].update( stat_loc )
            
            for idballoon, balloon in enumerate(keys):
            
                    if( (idballoon == 0 and not options_source['rotation']) ):
                            continue
                            
                    if ( options_source['rotation']):
                            if balloon == key_balloon:
                                    continue
            
                    if(options_source['rotation']):
                            distance = x['balloons'][balloon]['azimuth'][0]
                            azimuth  = x['balloons'][balloon]['azimuth'][1]
                            azimuth_rotation = (azimuth_balloon-azimuth) * np.pi / 180.
                            x_, y_ = distance*np.cos(azimuth_rotation), distance*np.sin(azimuth_rotation)
                            
                    else:
                            x_, y_ = compute_coordinate_USE(x['balloons'][balloon]['azimuth'])
                    
                    stat_loc, id_in  = create_stations(x_, y_, x['balloons'][balloon]['balloon']['Alt'], balloon, id_in, t_chosen = options_source['t_chosen'], balloon=True)
                    x['station_tab'].update( stat_loc )
                 
    else:
        lat_max, lat_min = options_source['lat_max']-x['LAT'], options_source['lat_min']-x['LAT']
        lon_max, lon_min = options_source['lon_max']-x['LON'], options_source['lon_min']-x['LON']

    ## Add mechanism to DataFrame
    x['mt'] = mt
    x['M']  = mt.m6_up_south_east()
    x['M'] /= 1.e15 # Convert N.m = m^2.kg/s^2 to right unit (everything is in km and g/cm^3)
            
    ## Determine domain boundaries   
    dchosen = options_source['nb_kxy']
    x['domain'] = get_domain(x['LAT'], x['LON'], lat_max, lat_min, lon_max, lon_min, dimension, dchosen = dchosen)
    #print('nbkxy: ', abs( x['domain']['xmax'] - x['domain']['xmin'] )/x['domain']['dx'])
    
    
    ## If domain too large we have to reduce the high frequency bound otherwise aliasing
    dist_x = abs( x['domain']['xmax'] - x['domain']['xmin'] )
    dist_y = abs( x['domain']['ymax'] - x['domain']['ymin'] )
    
    ## Ugly hack to update frequency range if propagation path too long
    if data_GPS.size > 0:
        if (dist_x/1000. >= 100. or dist_y/1000. >= 100.) and sub_df.iloc[loc_time]['Alt']/1000. > 10.:
            x['coef_high_freq'] = 3.5
        else:
            x['coef_high_freq'] = 5.
            
    ## Changed on 2/1/2021
    x['coef_high_freq'] = options_source['coef_high_freq']

    return x

def compute_time(x, startdate):

    x['startdate'] = UTCDateTime(startdate) + x['GPSTime(s)']
    
    return x

def compute_SAC(x, client, rotation, t_chosen, add_SAC, options_IRIS):

    start_day = x['startdate']
    
    inventory = client.get_stations(network=options_IRIS['network'], channel=options_IRIS['channel'], 
                                    starttime=start_day, endtime=start_day + 100., 
                                    minlatitude=x['domain']['latmin'], maxlatitude=x['domain']['latmax'], 
                                    minlongitude=x['domain']['lonmin'], maxlongitude=x['domain']['lonmax'], 
                                    level='response')
    
    ## If IRIS stations not wanted, we return already 
    if(not add_SAC):
        return x
    
    ## Check if row contains balloon information
    if x['balloons']:
        keys = [ikey for ikey in x['balloons'].keys()]
        azimuth_balloon = x['balloons'][keys[0]]['azimuth'][1]
    
    id_in = len(x['station_tab'].keys())
    
    ## Seismic stations
    done_tab = []
    for name_SAC in inventory.get_contents()['channels']:
    
            stat = name_SAC.split('.')[1]
            
            ## Skip stations that have already been processed
            if(stat in done_tab):
                    continue
              
            ## Skip irrelevant channels
            comp = name_SAC.split('.')[-1]      
            if(comp[0] == 'V' or comp[0] == 'L'):
                    continue
                      
            done_tab.append( stat )
            
            coordinates = inventory.get_coordinates(name_SAC)
            azimuth     = gps2dist_azimuth(x['LAT'], x['LON'], coordinates['latitude'], coordinates['longitude'])
            x_, y_      = compute_coordinate_USE(azimuth)
            
            ## 1) Rotate station coordinates in the source-balloon reference system
            min_dist__ = 1e10
            if x['balloons']:
                if(rotation):
                        azimuth_rotation = (azimuth_balloon - azimuth[1]) * np.pi / 180.
                        x_, y_ = azimuth[0]*np.cos(azimuth_rotation), azimuth[0]*np.sin(azimuth_rotation)
                
                for balloon__ in x['balloons'].keys():
                        dist__ = gps2dist_azimuth(x['balloons'][balloon__]['balloon']['Lat'], x['balloons'][balloon__]['balloon']['Lon'], 
                                                  coordinates['latitude'], coordinates['longitude'])
                        min_dist__ = min(dist__[0]/1000., min_dist__)
            
            ## 2) Remove stations that are too far from balloon            
            if min_dist__ > 45 and x['balloons']:
                    continue
                    
            ## Add ground station to dataframe
            z_      = 0.
            name_in = stat

            stat_loc, id_in    = create_stations(x_, y_, z_, name_in, id_in, t_chosen = t_chosen)
            x['station_tab'].update( stat_loc )
    
    ## Exit message if not station found
    if not x['station_tab']:
        sys.exit('No station found for mechanism: ' + str(x['EVID']))
    
    return x

def compute_non_SAC(x, options_IRIS):

    ## Add custom stations
    if options_IRIS['stations']:
        x['station_tab'].update( options_IRIS['stations'] )
        
    return x

def modify_dip(dip, d_rake):
    
    dip_mod  = (dip-45.) - np.sign(dip-45.)*abs(d_rake)
    if((dip-45. < 0. and dip_mod > 0.) or (dip-45. >= 0. and dip_mod < 0.)):
            dip = 45.
    else:
            dip = 45. + dip_mod
            
    return dip

def add_mechanism(x, type):

    err  = x['FPUC']
    rake = x['RAKE'] 
    dip  = x['DIP']
    depth = x['DEPTH'] 
    if type == 'min':
            depth += x['ERDEP']
            if(abs(rake) > 90.):
                    if(rake > 0):
                            d_rake = 180 - (rake+err)
                            ## If the increment in rake makes final rake > 180deg
                            ## we set rake == 180 and we modify the dip up to 90deg (pure strike-slip)
                            if(d_rake < 0):
                                    rake  = 180.
                                    dip   = max(90., dip+abs(d_rake))
                            else:
                                    rake += err
                    else:
                            d_rake = -180 - (rake-err)
                            if(d_rake > 0):
                                    rake = -180.
                                    dip  = max(90., dip+abs(d_rake))
                            else:
                                    rake -= err
            else:
                    if(rake > 0):
                            d_rake = (rake-err)
                            ## If the increment in rake makes final rake > 180deg
                            ## we set rake == 180 and we modify the dip up to 90deg (pure strike-slip)
                            if(d_rake < 0):
                                    rake  = 0.
                                    dip   = max(90., dip+abs(d_rake))
                            else:
                                    rake -= err
                    else:
                            d_rake = (rake+err)
                            if(d_rake > 0):
                                    rake = 0.
                                    dip  = max(90., dip+abs(d_rake))
                            else:
                                    rake += err
    else:
            depth -= max(x['ERDEP'], 0.)
            if(abs(rake) > 90.):
                    if(rake > 0.):
                            d_rake = 90 - (rake-err)
                            if(d_rake < 90):
                                    rake = 90.
                                    dip = modify_dip(dip, d_rake)
                            else:
                                    rake -= err
                    else:
                            d_rake = -90 - (rake+err)  
                            if(d_rake < 0):
                                    rake = -90.
                                    dip = modify_dip(dip, d_rake)
                            else:
                                    rake += err
            else:
                    if(rake > 0.):
                            d_rake = 90 - (rake+err)
                            if(d_rake < 0.):
                                    rake = 90.
                                    dip = modify_dip(dip, d_rake)
                            else:
                                    rake += err
                    else:
                            d_rake = -90 - (rake-err)
                            if(d_rake > 0.):
                                    rake = -90.
                                    dip = modify_dip(dip, d_rake)
                                    
                            else:
                                    rake -= err
                               
    x['DIP']  = dip
    x['RAKE'] = rake
    x['DEPTH'] = depth
    
    return x

def add_one_mecha(dict_mecha, template):

    ## Initialize new DataFrame entry
    source_characteristics = {}
    for key in template:
        source_characteristics[key] = np.nan
    
    ## Update relevant source parameters    
    source_characteristics.update( {
            'EVID': dict_mecha['id'],
            '#YYY/MM/DD': dict_mecha['time'].strftime('%Y/%m/%d'),
            'HH:mm:SS.ss': dict_mecha['time'].strftime('%H:%M:%S.%f'),
            'MAG': dict_mecha['mag'],
            'LAT': dict_mecha['lat'],
            'LON': dict_mecha['lon'],
            'DEPTH': dict_mecha['depth'],
            'STRIKE': dict_mecha['strike'],
            'DIP': dict_mecha['dip'],
            'RAKE': dict_mecha['rake'],
        } )
        
    return pd.DataFrame([source_characteristics])

def add_all_custom_mecha(sources, template):
    
    mechanisms_data_custom = pd.DataFrame()
    for source in sources:
        mechanisms_data_custom = mechanisms_data_custom.append( add_one_mecha(source, template) )
        
    return mechanisms_data_custom

def load_raw_mecha(options_source):

    mechanisms_data = pd.DataFrame()
    for idir in options_source['DIRECTORY_MECHANISMS']:
        mechanism_data = pd.read_csv(idir, header=[0], delim_whitespace=True)
        mechanisms_data = mechanisms_data.append( mechanism_data )

    ## Add mechanisms created by the user
    template = ['EVID', '#YYY/MM/DD', 'HH:mm:SS.ss', 'ET', 'GT', 'MAG', 'M', 'LAT', 'LON', 
                'DEPTH', 'Q', 'NPH', 'WRMS', 'ERHOR', 'ERDEP', 'ERTIME', 'STRIKE', 'DIP', 
                'RAKE', 'FPUC', 'APUC', 'NPPL', 'MFRAC', 'FMQ', 'PROB', 'STDR', 'NSPR', 'MAVG']
    mechanisms_data = mechanisms_data.append( add_all_custom_mecha(options_source['sources'], template) )
    mechanisms_data.reset_index(drop=True, inplace=True)
    
    return mechanisms_data

def load_source_mechanism_IRIS(options_source, options_IRIS, dimension =3, add_SAC=False, 
                               add_perturbations=False, specific_events=[], options_balloon={}):
    
    ## Collect balloon information if any
    data_GPS = pd.DataFrame()
    if options_balloon:
        for idir in options_balloon['DIR_BALLOON_GPS']:
            data = pd.read_csv(idir[0], header=[0])   
            data.columns = ['GPSTime(s)', 'Lat', 'Lon', 'Alt'] 
            data['name']      = idir[0].split('/')[-1].split('_GPS')[0]
            data = data.apply(compute_time, axis=1, args=[idir[1]])
            data_GPS = data_GPS.append( data.copy() )

    ## Add mechanism from .csv files
    mechanisms_data = load_raw_mecha(options_source)
    
    ## Update mechanism parameters and add perturbations
    if(specific_events):
        mechanisms_data = mechanisms_data.loc[ mechanisms_data['EVID'].isin(specific_events) ]
        if(not mechanisms_data.size > 0):
            sys.exit('Requested mechanism IDs in "specific_events" not found')
            
    mechanisms_data = mechanisms_data.apply(add_source_parameters, axis=1, args=[options_source, dimension, data_GPS])
    if options_balloon:
        mechanisms_data = mechanisms_data.loc[ mechanisms_data['any_balloon'] == True, : ]
    
    if(add_perturbations):
        mechanism_data_min = mechanisms_data.apply(add_mechanism, axis=1, args=['min']) 
        mechanism_data_min = mechanism_data_min.apply(add_source_parameters, axis=1, args=[options_source, dimension, data_GPS])
        mechanism_data_max = mechanisms_data.apply(add_mechanism, axis=1, args=['max']) 
        mechanism_data_max = mechanism_data_max.apply(add_source_parameters, axis=1, args=[options_source, dimension, data_GPS])
        
        mechanisms_data = mechanisms_data.append( mechanism_data_min.copy() )
        mechanisms_data = mechanisms_data.append( mechanism_data_max.copy() )
            
    ## Deallocate
    data_GPS, data = None, None
    
    ## Exit if after looping over all events, none have been selected
    if(not mechanisms_data.size > 0):
        sys.exit('No mechanisms found! Check list "specific_events"')
    
    ## Load stations from IRIS and custom dict
    if(add_SAC):
        client = Client("IRIS")
        mechanisms_data.apply(compute_SAC, axis=1, args=[client, options_source['rotation'], options_source['t_chosen'], add_SAC, options_IRIS])
    mechanisms_data.apply(compute_non_SAC, axis=1, args=[options_IRIS])
    
    ## Flag to say that these focal mechanisms are not perturbed
    mechanisms_data['perturbation'] = False
    
    return mechanisms_data
    
def compute_response_one_mecha(x, type_opti, Green_RW):
        
    keys_mechanism = ['stf', 'zsource', 'f0', 'M0', 'M', 'phi', 'mt']
    
    mecha   = x
    station = mecha['station_tab'][0]
    rtab    = np.array([station['xs']/1000.])
    phitab  = np.array([0.])
    type, unknown, mode_max, dimension_seismic = 'RW', 'v', -1, 3
    err = mecha['FPUC']
    errdepth = mecha['ERDEP']*1000.
    
    ## Setup perturbed mechanisms range
    mw = mecha['MAG']
    if(mw < 4.):
            mw = (2./3.)*mecha['MAG'] + 1.15
                    
    ## Setup a baseline mechanism
    mechanism = {}
    for key in keys_mechanism:
            mechanism[key] = mecha[key] 

    mt = mechanism['mt']
    if not type_opti in ['min', 'max']:
            
            strike = mecha['STRIKE']
            if type_opti == 'left_strike_slip':
                    dip, rake = 90., 0.
            elif type_opti == 'right_strike_slip':
                    dip, rake = 90., 180.
            elif type_opti == 'normal':
                    dip, rake = 45., -90.
            elif type_opti == 'reverse':
                    dip, rake = 45., 90
            else:
                    sys.exit('Fault type not recognized: ' + type_opti)
            
    else:
            Green_RW.update_mechanism(mechanism)   
            bounds = Bounds([0.-mecha['STRIKE'],0.-mecha['DIP'],-180.0-mecha['RAKE']], [360.-mecha['STRIKE'],90.-mecha['DIP'], 180.0-mecha['RAKE']])
            
            ## Solve minimization problem
            x0 = np.array([0., 0., 0.]) # Initial condition
            def constraint(x, err):
                    return err-np.sum(np.abs(x))
                    
            res = minimize(Green_RW.response_perturbed_solution, x0=x0, method="COBYLA", constraints=({"fun": constraint, "type": "ineq", 'args': (err,)}), args=(rtab, phitab, type, unknown, mode_max, dimension_seismic, type_opti), bounds=bounds)
            
            ## Compute a mechanism input to change the error simulation
            mechanism = Green_RW.get_mechanism()
            strike0, dip0, rake0 = mt.both_strike_dip_rake()[0]
            strike, dip, rake    = strike0 + res['x'][0], dip0 + res['x'][1], rake0 + res['x'][2]
            
    m0 = mt.scalar_moment()
    mt = mtm.MomentTensor(strike=strike, dip=dip, rake=rake, scalar_moment=m0)
    mechanism['M']  = mt.m6_up_south_east()
    mechanism['M'] /= 1.e15
    mechanism['mt'] = mt
    
    ## Change depth
    add = errdepth if type_opti == 'min' else -1*errdepth
    mechanism['zsource'] += add
    
    ## Update current dataframe row
    for key in ['zsource', 'M', 'mt']:
            x[key] = mechanism[key]  
    
    x['perturbation'] = True
    
    return x
    
def find_extreme_cases(mechanisms_data, get_normal_reverse_strike, Green_RW=None):

        import matplotlib.colors as colors
        from mpl_toolkits.axes_grid1 import make_axes_locatable
        from pyrocko import moment_tensor as mtm
        from pyrocko.moment_tensor import rotation_from_angle_and_axis
        from scipy.optimize import minimize, Bounds
        from scipy.optimize import LinearConstraint
        
        if get_normal_reverse_strike:
                mechanisms_data_strike  = mechanisms_data.apply(compute_response_one_mecha, axis=1, args=['left_strike_slip', Green_RW])
                mechanisms_data_normal  = mechanisms_data.apply(compute_response_one_mecha, axis=1, args=['normal', Green_RW])
                #mechanisms_data_reverse = mechanisms_data.apply(compute_response_one_mecha, axis=1, args=['reverse', Green_RW])
                
                mechanisms_data = mechanisms_data.append( mechanisms_data_strike.copy() )
                mechanisms_data = mechanisms_data.append( mechanisms_data_normal.copy() )
                #mechanisms_data = mechanisms_data.append( mechanisms_data_reverse.copy() )
                
        else:
                mechanisms_data_min = mechanisms_data.apply(compute_response_one_mecha, axis=1, args=['min', Green_RW])
                mechanisms_data_max = mechanisms_data.apply(compute_response_one_mecha, axis=1, args=['max', Green_RW])
                
                mechanisms_data = mechanisms_data.append( mechanisms_data_min.copy() )
                mechanisms_data = mechanisms_data.append( mechanisms_data_max.copy() )
        
        return mechanisms_data
        
## Station distribution
def display_map_stations(ID, station_tab, domain, new_folder):

    from adjustText import adjust_text
    
    fig, axs = plt.subplots(nrows=1, ncols=1)

    font = {'color':  'black',
            'weight': 'normal',
            'size': 9,
            }
    
    texts, xstats, ystats = [], [], []
    done = {}
    for stat_ in station_tab:
    
            stat = station_tab[stat_]
    
            if stat['name'] in done and not stat['comp'] == 'p':
                    continue
    
            xtext = stat['xs']/1000.
            ytext = stat['ys']/1000.
            xstats.append( ytext )
            ystats.append( xtext )
            
            if(stat['comp'] == 'p'):
                    axs.scatter(xtext, ytext, marker='o', zorder=10, c='tab:blue') 
                    
            axs.scatter(xtext, ytext, marker='^', zorder=5, c='tab:orange')
            
            if(not stat['name'] in done):
                    texts.append( axs.text(xtext, ytext, stat['name'], fontdict=font) )
            
            done[stat['name']] = True
    
    axs.axvline(domain['xmin']/1000., color='red', linestyle='--', zorder=0)
    axs.axvline(domain['xmax']/1000., color='red', linestyle='--', zorder=0)
    axs.axhline(domain['ymin']/1000., color='red', linestyle='--', zorder=0)
    axs.axhline(domain['ymax']/1000., color='red', linestyle='--', zorder=0)
    
    xstats.append( 0. )
    ystats.append( 0. )
    adjust_text(texts, xstats, ystats, arrowprops=dict(arrowstyle="->", color='r', lw=0.5))
    
    axs.scatter(0., 0., marker='*', c='black')
    axs.set_title('Event '+str(ID))
    axs.grid()
    axs.set_xlabel('West - East (km from source)')
    axs.set_ylabel('North - South (km from source)')
    
    fig.savefig( new_folder + '/distribution_station.pdf' )
   
def create_one_station(x, y, z, comp, name, id, data = None, file = None, t_chosen = [50.]):

    station = {
        'id': id,
        'name': name,
        'xs': x, 'ys': y, 'zs': z,
        't_chosen': t_chosen,
        'type_slice': 'xz',
        'comp': comp,
        'data': data,
        'file': file
        } 
    
    return station
   
def create_stations(x_in, y_in, z_in, name_in, id_in, t_chosen = [50.], balloon=False, data=[], only_data=False, this_is_specfem_3d=True):
                
        ## If data provided store in dict
        data_, file_ = {}, {}
        if data:
                found_data = False
                for  subdir, dirs, files in os.walk(data[0]):
                        for file in files:
                                filepath = subdir + os.sep + file
                                
                                if( data[1] in file ):
                                
                                        
                                
                                        comp  = file.split('.')[-1][-1]
                                        if not this_is_specfem_3d:
                                                if(z_in > 0.):
                                                        comp  = 'p' if comp == 'v' else 'v'

                                        comp_ = file.split('.')[-2][-1]
                                        if(comp == 'v'):
                                                comp = 'v' + comp_.lower()
                                
                                        found_data = True
                                        data_simu = pd.read_csv( filepath, delim_whitespace=True, header=None )
                                        
                                        data_simu.columns = ['t', 'amp']
                                        data_[comp] = data_simu.copy()
                                        file_[comp] = file
                
        station_tab = {}
        
        z_list    = [z_in, 0.]
        comp_list = ['vz']
        if(balloon):
                comp_list += ['p']
                #z_list    += [0.]
        
        x, y = x_in, y_in
        name = name_in
        id   = id_in
        for comp in comp_list:
                for z in z_list:
                        data_loc = np.array([])
                        file_loc = ''
                        if data_ and abs(z - z_list[0]) < 1e-5:
                                data_loc = data_[comp].values
                                file_loc = file_[comp]
                                
                        if only_data and data_loc.size == 0:
                                continue
                                
                        station_tab[id] = create_one_station(x, y, z, comp, name, id, data_loc, file_loc, t_chosen)
                        id += 1
        
        return station_tab, id
        
def save_mt(mt, new_folder):
        
        f = open(new_folder + '/mechanism.txt','w')
        f.write( str(mt) )
        f.close()