import matplotlib
import matplotlib as mpl
import matplotlib.pyplot as plt
import configparser
from matplotlib.widgets import Cursor
from energytracecapture import EnergyTraceCapture
import tkinter as tk
import sqlite3
import datetime
import os
import pathlib
# For stune captures
import tempfile
import subprocess
from threading import Thread
import gc
import time
from tkinter import filedialog as fd
from string import Template

APP_NAME = "TkET"

app_config = configparser.ConfigParser()
app_config['DEFAULT'] = {'CCSPath': 'C:/ti/ccs1240/',
                         'ObjectCompression': 'true',
                         'CaptureCache': 'true'}

# Path from ccs folder
stune_path_from_ccs = "/ccs/ccs_base/emulation/analysis/bin/stune/"
# By default, we run with the GUI
gui_mode = 1
previous_captures_db = "tket.sqlite"
file_settings = "tket.ini"
font_header = "Roboto 18 bold"
font_subheader = "Roboto 13 bold"
font_path = "Roboto 10 bold"
font_button = "Roboto 10"
header_padx = 10
header_pady = 10
header_borderwidth = 2
color_main_header = "#cc0000"
color_sub_header = "#115566"
color_select_button = "#4CAF50"
loading = 0
current_scaling = 1.0
current_offset = 200000
timestamp_scaling = 1000
ccxml_path = ""
capture_cache = []

root = tk.Tk()
#Tk variables
stringvar_duration = tk.StringVar()
stringvar_ccxmlpath = tk.StringVar()
stringvar_duration.set("1000")

matplotlib.use('TkAgg')

#TODO: Add unknown duration that just cycles
def thread_progressbar(name, duration):
    window_height = 80
    window_width = 1000
    window_loading = tk.Tk()
    window_loading.resizable(False, False)
    window_loading.geometry(str(window_width) + "x" + str(window_height))
    window_loading.iconbitmap("icon.ico")
    window_loading.title(name)
    canvas_progress = tk.Canvas(window_loading, height=window_height, width=window_width)
    canvas_progress.pack()
    progressbar = canvas_progress.create_rectangle(0, 0, 0, window_height, fill=color_select_button)

    step_value = window_width / (duration / 100)
    i = 0

    while i < window_width:
            x0, y0, x1, y1 = canvas_progress.coords(progressbar)
            x1 = x0 + i
            y1 = window_height
            canvas_progress.coords(progressbar, x0, y0, x1, y1)
            i += step_value
            window_loading.update()
            time.sleep(100 / 1000)

    window_loading.destroy()
    return

def create_progressbar(name, duration):
    t = Thread(target=thread_progressbar, args=[name, duration])
    t.start()
    return

# We want to always cache the captures so that we can reopen them quickly
def cache_capture(filename):
    for capture in capture_cache:
        if capture.name == filename:
            # -1: Already cached
            return -1
        
    if gui_mode:
        # Guesswork as to how long it takes..
        create_progressbar("Loading capture...", 1000)

    capture_cache.append(EnergyTraceCapture(filename))

    return 0

def fetch_capture_from_cache(filename):
    for capture in capture_cache:
        if capture.name == filename:
            return capture
    # -1: We somehow did not find capture in cache
    return -1
    

def show_capture(filename):
    global loading

    etcap = fetch_capture_from_cache(filename)
    if (etcap == -1):
        # Capture not found
        return -1
    
    gc.collect()
    
    f = plt.figure()
    f.suptitle(etcap.name)
    f.canvas.manager.set_window_title(etcap.name)
    f.canvas.mpl_connect('close_event', cb_onclose_figure)
    #plt.xlabel('Time')
    
    ax_current = plt.subplot(211)
    ax_current.set_facecolor("dimgrey")
    ax_current.set_title("Current")
    ax_current.set_ylabel("nA")
    ax_current.axis([0, etcap.timestamp[-1] / timestamp_scaling, (etcap.min_current_value - current_offset) / current_scaling, (etcap.max_current_value + current_offset) / current_scaling])
    ax_current.grid(color="forestgreen")
    ax_current.ticklabel_format(style='plain')
    plt.plot(etcap.timestamp / timestamp_scaling, etcap.current / current_scaling, c="limegreen", linewidth=1, figure=f)
    
    ax_energy = plt.subplot(212, sharex=ax_current)
    ax_energy.set_facecolor("dimgrey")
    ax_energy.set_title("Energy")
    ax_energy.axis([0, etcap.timestamp[-1] / timestamp_scaling , etcap.min_energy_value, etcap.max_energy_value])
    ax_energy.set_ylabel('mJ')
    ax_energy.grid(color="forestgreen")
    plt.plot(etcap.timestamp / timestamp_scaling , etcap.energy, c="limegreen", linewidth=1, figure=f)

    cursor = Cursor(ax_energy, useblit=True, color='red', linewidth=2)

    f.show()
    loading = 0

def select_capture_file():
    et_extensions = ['*.profxml', "*.csv"]
    filetypes = [("EnergyTrace captures", et_extensions)]

    filename = fd.askopenfilenames(
        title='Open an EnergyTrace file',
        initialdir='/',
        filetypes=filetypes)

    for capture in filename:
        cache_capture(capture)
        current_date_time = datetime.datetime.now()
        insert_capture_db(capture, current_date_time)
        show_capture(capture)

def select_ccxml_file():
    global ccxml_path

    ccxml_extensions = ['*.ccxml']
    filetypes = [("Target configuration", ccxml_extensions)]

    filename = fd.askopenfilename(
        title='Open a target configuration file',
        initialdir='/',
        filetypes=filetypes)

    if filename:
        ccxml_path = filename
        stringvar_ccxmlpath.set(os.path.basename(filename))

# TODO: Save the file to a select location
def record_stune_session():
    global app_config, ccxml_path, stune_path_from_ccs
    
    if stringvar_ccxmlpath.get() == "":
        tk.messagebox.showerror('TkET', 'Error: Missing target configuration file!')
        return
    
    stune_template = Template("connect --device $device --config $config xds\nenergytrace --out=$csv --duration=$duration et\n")

    # Puts the file into RAM, hopefully?
    temp_csv_file = tempfile.NamedTemporaryFile(mode='w+b', suffix=".csv", delete=False)

    # Still more assumptions about the devices...
    device = stringvar_ccxmlpath.get().replace(".ccxml", "")

    # TODO: Check what is in stringvar
    stune_command = stune_template.substitute(device=device, config=ccxml_path, csv=temp_csv_file.name, duration=stringvar_duration.get()).encode()
    stune_path = pathlib.Path(app_config["tket.settings"]["CCSPath"] + stune_path_from_ccs, "stune.exe")
    try:
        p = subprocess.Popen([stune_path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, cwd=stune_path.parent)
        create_progressbar("Recording...", int(stringvar_duration.get()))
        stdout = p.communicate(input=stune_command)
    except:
        tk.messagebox.showerror('TkET', 'Error: Could not start stune.exe. Are sure you selected the correct CCS path?')
        return

    cache_capture(temp_csv_file.name)
    show_capture(temp_csv_file.name)
    


def fetch_previous_capture_db():
    # Will create DB if it does not exists
    con = sqlite3.connect(previous_captures_db)
    cur = con.cursor()
    
    rows = []
    # Check that database exists
    try:
        cur.execute("SELECT name, access_date FROM captures ORDER BY access_date")
        rows = cur.fetchall()
    except sqlite3.OperationalError:
        cur.execute("CREATE TABLE captures(name, access_date)")

    cur.close()
    con.close()

    return rows

def insert_capture_db(name, access_date):
    con = sqlite3.connect(previous_captures_db)
    cur = con.cursor()
    # Check if record already exists. If so, update access date

    insert_query = """INSERT INTO captures VALUES (?, ?);"""
    cur.execute(insert_query, (name, access_date))
    
    con.commit()
    cur.close()
    con.close()

def read_config(file_settings, config):
    if os.path.exists(file_settings):
        config.read(file_settings)
    else:
        # Ask about ccs location
        foldername = fd.askdirectory(
        title='Select Code Composer Studio folder',
        initialdir='C:/ti')

        if foldername:
            # TODO: Make menu for other settings, but not there
            config['tket.settings'] = {}
            config['tket.settings']['CCSPath'] = foldername
            with open(file_settings, 'w') as configfile:
                config.write(configfile)

def cb_list_previous_files_onselect(evt):
    global loading

    if loading == 0:
        loading = 1
        w = evt.widget
        index = int(w.curselection()[0])
        value = w.get(index)
        cache_capture(value[0])
        show_capture(value[0])

def cb_onclose_figure(event):
    for i in plt.get_fignums():
        print(i)
    gc.collect()

# Window init
root.title(APP_NAME)
root.iconbitmap("icon.ico")
root.resizable(False, False)
root.geometry('485x485')
root.config(background="#f2f2f2")

gc.enable()

# ================================== HEADER ===================================
frame_header = tk.Frame(root)
frame_header.pack(side=tk.TOP, expand=True, fill=tk.X, anchor=tk.N, pady=0)

lbl_appname = tk.Label(frame_header, text=" " + APP_NAME, relief=tk.FLAT, bg=color_main_header, fg="white", font=font_header, anchor=tk.W)
lbl_appname.pack(side=tk.LEFT, expand=True, fill=tk.X)

# ==================== SELECT MENU FRAME ======================================
frame_top_level_select = tk.Frame(root, bg="white", relief=tk.RAISED, borderwidth=header_borderwidth)
frame_top_level_select.pack(side=tk.TOP, expand=True, fill=tk.BOTH, anchor=tk.N, padx=header_padx, pady=header_pady)

#      =============== SELECT MENU HEADER =====================================
frame_select_header = tk.Frame(frame_top_level_select)
frame_select_header.pack(side=tk.TOP, expand=True, fill=tk.X, anchor=tk.N)

lbl_subhead_select = tk.Label(frame_select_header, text=" Open existing capture", relief=tk.FLAT, bg=color_sub_header, fg="white", font=font_subheader, anchor=tk.W)
lbl_subhead_select.pack(side=tk.LEFT, expand=True, fill=tk.X)

#      =============== SELECT MENU ============================================
frame_select = tk.Frame(frame_top_level_select , bg="white")
frame_select.pack(side=tk.TOP, pady=10)

# open button
open_button = tk.Button(
    frame_select,
    text='Select',
    command=select_capture_file,
    bg=color_select_button,
    fg="white",
    font=font_button
)

lbl_selbutton = tk.Label(frame_select, text=" a .profxml or .csv file to inspect", font=font_subheader, fg="#666666", bg="white")
open_button.grid(row=0, column=1, sticky=tk.NSEW, columnspan=1)
lbl_selbutton.grid(row=0, column=2, sticky=tk.NSEW)

# ==================== RECORD MENU FRAME ======================================
frame_top_level_record = tk.Frame(root, bg="white", relief=tk.RAISED, borderwidth=header_borderwidth)
frame_top_level_record.pack(side=tk.TOP, expand=True, fill=tk.BOTH, anchor=tk.N, padx=header_padx, pady=header_pady)

#      =============== RECORD MENU HEADER =====================================
frame_record_header = tk.Frame(frame_top_level_record)
frame_record_header.pack(side=tk.TOP, expand=True, fill=tk.X, anchor=tk.N)

lbl_subhead_record = tk.Label(frame_record_header, text=" New session", relief=tk.FLAT, bg=color_sub_header, fg="white", font=font_subheader, anchor=tk.W)
lbl_subhead_record.pack(side=tk.LEFT, expand=True, fill=tk.X)

#      =============== RECORD MENU =============================================

frame_record = tk.Frame(frame_top_level_record , bg="white")
frame_record.pack(side=tk.TOP, pady=10)

# select ccxml file button
select_ccxml_button = tk.Button(
    frame_record,
    text='Select',
    command=select_ccxml_file,
    bg=color_select_button,
    fg="white",
    font=font_button
)

lbl_filepath = tk.Label(frame_record, textvariable=stringvar_ccxmlpath, font=font_path, fg=color_sub_header, bg="white")
lbl_ccxmlbutton = tk.Label(frame_record, text=" a target configuration file (.ccxml) ", font=font_subheader, fg="#666666", bg="white")
entry_duration = tk.Entry(frame_record, textvariable=stringvar_duration, font=font_path, fg=color_sub_header, width=5)
lbl_duration = tk.Label(frame_record, text=" mS (Capture duration) ", font=font_subheader, fg="#666666", bg="white")

# record button
record_button = tk.Button(
    frame_record,
    text='Record',
    command=record_stune_session,
    bg=color_main_header,
    fg="white",
    font=font_button
)

lbl_filepath.grid(row=0, column=1, columnspan=3)
select_ccxml_button.grid(row=1, column=1, sticky=tk.NSEW, columnspan=1, pady=10)
lbl_ccxmlbutton.grid(row=1, column=2, sticky=tk.NSEW)
entry_duration.grid(row=2, column=1, sticky=tk.NSEW)
lbl_duration.grid(row=2, column=2, sticky=tk.W)
record_button.grid(row=3, column=1, sticky=tk.NSEW, columnspan=3, pady=10)

# ================================== PREVIOUS FILES HEADER ====================

frame_top_level_previous = tk.Frame(root, bg="white", relief=tk.RAISED, borderwidth=header_borderwidth)
frame_top_level_previous.pack(side=tk.TOP, expand=True, fill=tk.BOTH, anchor=tk.N, padx=header_padx, pady=header_pady)

#      ============================= PREVIOUS FILES =============================
frame_previous = tk.Frame(frame_top_level_previous)
frame_previous.pack(side=tk.TOP, expand=True, fill=tk.X, anchor=tk.N)

lbl_subhead = tk.Label(frame_previous, text=" Previous files", relief=tk.FLAT, bg=color_sub_header, fg="white", font=font_subheader, anchor=tk.W)


list_previous_files = tk.Listbox(frame_previous, name='list_previous_files')
list_previous_files.bind('<<ListboxSelect>>', cb_list_previous_files_onselect)

captures = fetch_previous_capture_db()

capture_index = 0
for capture in captures:
    list_previous_files.insert(capture_index, capture)
    capture_index += 1

lbl_subhead.pack(side=tk.TOP, expand=True, fill=tk.X)
list_previous_files.pack(side=tk.BOTTOM, expand=True, fill=tk.BOTH, anchor=tk.S)

# Now read config
read_config(file_settings=file_settings, config=app_config)

# run the application
root.mainloop()