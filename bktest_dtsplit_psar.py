import sys
import json
import misc
import data_handler as dh
import pandas as pd
import numpy as np
import strategy as strat
import datetime
import backtest
from base import *

def dual_thrust_sim( mdf, config):
    close_daily = config['close_daily']
    marginrate = config['marginrate']
    offset = config['offset']
    k = config['param'][0]
    win = config['param'][1]
    multiplier = config['param'][2]
    f = config['param'][3]
    pos_update = config['pos_update']
    pos_class = config['pos_class']
    pos_args  = config['pos_args']
    proc_func = config['proc_func']
    proc_args = config['proc_args']
    start_equity = config['capital']
    chan_func = config['chan_func']
    chan_high = eval(chan_func['high']['func'])
    chan_low  = eval(chan_func['low']['func'])
    tcost = config['trans_cost']
    unit = config['unit']
    SL = config['stoploss']
    min_rng = config['min_range']
    chan = config['chan']
    use_chan = config['use_chan']
    no_trade_set = config['no_trade_set']
    ll = mdf.shape[0]
    xdf = proc_func(mdf, **proc_args)
    if win == -1:
        tr= pd.concat([xdf.high - xdf.low, abs(xdf.close - xdf.close.shift(1))], 
                       join='outer', axis=1).max(axis=1)
    elif win == 0:
        tr = pd.concat([(pd.rolling_max(xdf.high, 2) - pd.rolling_min(xdf.close, 2))*multiplier, 
                        (pd.rolling_max(xdf.close, 2) - pd.rolling_min(xdf.low, 2))*multiplier,
                        xdf.high - xdf.close, 
                        xdf.close - xdf.low], 
                        join='outer', axis=1).max(axis=1)
    else:
        tr= pd.concat([pd.rolling_max(xdf.high, win) - pd.rolling_min(xdf.close, win), 
                       pd.rolling_max(xdf.close, win) - pd.rolling_min(xdf.low, win)], 
                       join='outer', axis=1).max(axis=1)
    xdf['TR'] = tr
    xdf['chan_h'] = chan_high(xdf['high'], chan, **chan_func['high']['args'])
    xdf['chan_l'] = chan_low(xdf['low'], chan, **chan_func['low']['args'])
    xdf['MA'] = pd.rolling_mean(xdf.close, chan)
    xdata = pd.concat([xdf['TR'].shift(1), xdf['MA'].shift(1),
                       xdf['chan_h'].shift(1), xdf['chan_l'].shift(1),
                       xdf['open'], xdf['date_idx']], axis=1, keys=['TR','MA', 'chanH', 'chanL', 'dopen', 'date']).fillna(0)
    mdf = mdf.join(xdata, how = 'left').fillna(method='ffill')
    mdf['pos'] = pd.Series([0]*ll, index = mdf.index)
    mdf['cost'] = pd.Series([0]*ll, index = mdf.index)
    curr_pos = []
    closed_trades = []
    end_d = mdf.index[-1].date
    #prev_d = start_d - datetime.timedelta(days=1)
    tradeid = 0
    xslice = BaseObject(open = 0, close = 0, high = 1000000, low = 0, pid = -1)
    need_update = False
    for dd in mdf.index:
        mslice = mdf.ix[dd]
        min_id = mslice.min_id
        min_cnt = (min_id-300)/100 * 60 + min_id % 100 + 1
        if len(curr_pos) == 0:
            pos = 0
        else:
            pos = curr_pos[0].pos
        mdf.ix[dd, 'pos'] = pos
        if (mslice.TR == 0) or (mslice.MA == 0):
            continue
        d_open = mslice.dopen
        rng = max(min_rng * d_open, k * mslice.TR)
        if (d_open <= 0):
            continue
        buytrig  = d_open + rng
        selltrig = d_open - rng
        if 'reset_margin' in pos_args:
            pos_args['reset_margin'] = mslice.TR * SL
        if mslice.MA > mslice.close:
            buytrig  += f * rng
        elif mslice.MA < mslice.close:
            selltrig -= f * rng
        if (min_id >= config['exit_min']) and (close_daily or (mslice.date == end_d)):
            if (pos != 0):
                curr_pos[0].close(mslice.close - misc.sign(pos) * offset , dd)
                tradeid += 1
                curr_pos[0].exit_tradeid = tradeid
                closed_trades.append(curr_pos[0])
                curr_pos = []
                mdf.ix[dd, 'cost'] -=  abs(pos) * (offset + mslice.close*tcost) 
                pos = 0
        elif min_id not in no_trade_set:
            if (pos!=0):
                exit_flag = False
                if (curr_pos[0].check_exit( mslice.close, 0 )):
                    curr_pos[0].close(mslice.close-offset*misc.sign(pos), dd)
                    tradeid += 1
                    curr_pos[0].exit_tradeid = tradeid
                    closed_trades.append(curr_pos[0])
                    curr_pos = []
                    mdf.ix[dd, 'cost'] -=  abs(pos) * (offset + mslice.close*tcost)    
                    pos = 0
                elif pos_update and need_update:
                    curr_pos[0].update_bar(xslice)
            if (mslice.high >= buytrig) and (pos ==0 ):
                if (use_chan == False) or (mslice.high > mslice.chanH):
                    new_pos = pos_class([mslice.contract], [1], unit, mslice.close + offset, selltrig, **pos_args)
                    #print mslice.close, mslice.TR, buytrig, selltrig
                    tradeid += 1
                    new_pos.entry_tradeid = tradeid
                    new_pos.open(mslice.close + offset, dd)
                    curr_pos.append(new_pos)
                    pos = unit
                    mdf.ix[dd, 'cost'] -=  abs(pos) * (offset + mslice.close*tcost)
            elif (mslice.low <= selltrig) and (pos ==0 ):
                if (use_chan == False) or (mslice.low < mslice.chanL):
                    new_pos = pos_class([mslice.contract], [1], -unit, mslice.close - offset, buytrig, **pos_args)
                    #print mslice.close, mslice.TR, buytrig, selltrig
                    tradeid += 1
                    new_pos.entry_tradeid = tradeid
                    new_pos.open(mslice.close - offset, dd)
                    curr_pos.append(new_pos)
                    pos = -unit
                    mdf.ix[dd, 'cost'] -= abs(pos) * (offset + mslice.close*tcost)
        mdf.ix[dd, 'pos'] = pos
        if xslice.pid != min_cnt / config['pos_freq']:
            if xslice.pid >= 0:
                need_update = True
            xslice.open = mslice.open
            xslice.high = mslice.high
            xslice.low  = mslice.low
            xslice.close = mslice.close
            xslice.pid = mslice.min_id / config['pos_freq']
        else:
            xslice.high = max(xslice.high, mslice.high)
            xslice.low  = min(xslice.low, mslice.low)
            xslice.close = mslice.close
            
    (res_pnl, ts) = backtest.get_pnl_stats( mdf, start_equity, marginrate, 'm')
    res_trade = backtest.get_trade_stats( closed_trades )
    res = dict( res_pnl.items() + res_trade.items())
    return (res, closed_trades, ts)


def gen_config_file(filename):
    sim_config = {}
    sim_config['sim_func']  = 'bktest_dtsplit_psar.dual_thrust_sim'
    sim_config['scen_keys'] = ['param']
    sim_config['sim_name']   = 'DTsplit'
    sim_config['products']   = ['m', 'RM', 'y', 'p', 'a', 'rb', 'SR', 'TA', 'MA', 'i', 'ru', 'j', 'jm', 'ag', 'cu', 'au' ]
    sim_config['start_date'] = '20141101'
    sim_config['end_date']   = '20151118'
    sim_config['param']  =  [
            (0.5, 0, 0.5, 0.0), (0.6, 0, 0.5, 0.0), (0.7, 0, 0.5, 0.0), (0.8, 0, 0.5, 0.0), \
            (0.9, 0, 0.5, 0.0), (1.0, 0, 0.5, 0.0), (1.1, 0, 0.5, 0.0), \
            (0.5, 1, 0.5, 0.0), (0.6, 1, 0.5, 0.0), (0.7, 1, 0.5, 0.0), (0.8, 1, 0.5, 0.0), \
            (0.9, 1, 0.5, 0.0), (1.0, 1, 0.5, 0.0), (1.1, 1, 0.5, 0.0), \
            (0.2, 2, 0.5, 0.0), (0.25,2, 0.5, 0.0), (0.3, 2, 0.5, 0.0), (0.35, 2, 0.5, 0.0),\
            (0.4, 2, 0.5, 0.0), (0.45, 2, 0.5, 0.0),(0.5, 2, 0.5, 0.0), \
            #(0.2, 4, 0.5, 0.0), (0.25, 4, 0.5, 0.0),(0.3, 4, 0.5, 0.0), (0.35, 4, 0.5, 0.0),\
            #(0.4, 4, 0.5, 0.0), (0.45, 4, 0.5, 0.0),(0.5, 4, 0.5, 0.0),\
            ]
    sim_config['pos_class'] = 'strat.ParSARTradePos'
    sim_config['proc_func'] = 'dh.day_split'
    sim_config['offset']    = 1
    chan_func = {'high': {'func': 'pd.rolling_max', 'args':{}},
                 'low':  {'func': 'pd.rolling_min', 'args':{}},
                 }
    config = {'capital': 10000,
              'chan': 10,
              'use_chan': False,
              'trans_cost': 0.0,
              'close_daily': False,
              'unit': 1,
              'stoploss': 0.0,
              'min_range': 0.003,
              'proc_args': {'minlist':[1500]},
              'pos_args': { 'af': 0.02, 'incr': 0.02, 'cap': 0.2},
              'pos_update': True,
              'chan_func': chan_func,
              'pos_freq':60,
              }
    sim_config['config'] = config
    with open(filename, 'w') as outfile:
        json.dump(sim_config, outfile)
    return sim_config

if __name__=="__main__":
    args = sys.argv[1:]
    if len(args) < 1:
        print "need to input a file name for config file"
    else:
        gen_config_file(args[0])
    pass
