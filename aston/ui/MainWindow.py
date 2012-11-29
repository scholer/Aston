import os.path as op
from PyQt4 import QtGui

from aston.ui.aston_ui import Ui_MainWindow
from aston.ui.FilterWindow import FilterWindow
from aston.ui.MainPlot import Plotter
from aston.ui.SpecPlot import SpecPlotter

from aston.Database import AstonFileDatabase
from aston.Database import AstonDatabase
from aston.FileTable import FileTreeModel
from aston.Math.Integrators import waveletIntegrate, statSlopeIntegrate


class AstonWindow(QtGui.QMainWindow):
    def __init__(self, parent=None):
        QtGui.QWidget.__init__(self, parent)
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        ##my icon! TODO: make an icon
        #icn_path = op.join(op.curdir,'aston','ui','icons','aston.png')
        #self.setIcon(QtGui.QIcon(icn_path))

        #quick fix for Mac OS menus
        self.ui.actionSettings.setMenuRole(QtGui.QAction.NoRole)

        #set up the grouping for the dock widgets
        self.tabifyDockWidget(self.ui.filesDockWidget, self.ui.settingsDockWidget)
        self.tabifyDockWidget(self.ui.filesDockWidget, self.ui.spectraDockWidget)
        self.tabifyDockWidget(self.ui.filesDockWidget, self.ui.methodDockWidget)
        self.tabifyDockWidget(self.ui.filesDockWidget, self.ui.compoundDockWidget)
        self.ui.filesDockWidget.raise_()

        #connect the menu logic
        self.ui.actionOpen.triggered.connect(self.openFolder)
        self.ui.actionExportChromatogram.triggered.connect(self.exportChromatogram)
        self.ui.actionExportSpectra.triggered.connect(self.exportSpectrum)
        self.ui.actionExportSelectedItems.triggered.connect(self.exportItems)
        self.ui.actionQuickIntegrate.triggered.connect(self.quickIntegrate)
        self.ui.actionEditFilters.triggered.connect(self.showFilterWindow)
        self.ui.actionRevert.triggered.connect(self.revertChromChange)
        self.ui.actionQuit.triggered.connect(QtGui.qApp.quit)

        #hook up the windows to the menu
        self.ui.actionFiles.triggered.connect(self.updateWindows)
        self.ui.actionSettings.triggered.connect(self.updateWindows)
        self.ui.actionSpectra.triggered.connect(self.updateWindows)
        self.ui.actionMethods.triggered.connect(self.updateWindows)
        self.ui.actionCompounds.triggered.connect(self.updateWindows)
        self.ui.filesDockWidget.visibilityChanged.connect(self.updateWindowsMenu)
        self.ui.settingsDockWidget.visibilityChanged.connect(self.updateWindowsMenu)
        self.ui.spectraDockWidget.visibilityChanged.connect(self.updateWindowsMenu)
        self.ui.methodDockWidget.visibilityChanged.connect(self.updateWindowsMenu)
        self.ui.compoundDockWidget.visibilityChanged.connect(self.updateWindowsMenu)
        self.ui.settingsDockWidget.setVisible(False)
        self.ui.compoundDockWidget.setVisible(False)
        self.ui.methodDockWidget.setVisible(False)

        #hook up the search box
        self.ui.lineEdit.textChanged.connect(self.updateSearch)

        #create the things that keep track of how the plots should look
        self.plotter = Plotter(self)
        self.specplotter = SpecPlotter(self)

        #flesh out the settings menu
        color_menu = QtGui.QMenu(self.ui.menuSettings)
        self._add_opts_to_menu(color_menu, \
          self.plotter.availColors(), self.set_color_scheme)
        self.ui.actionColor_Scheme.setMenu(color_menu)

        self.ui.actionLegend.triggered.connect(self.set_legend)

        style_menu = QtGui.QMenu(self.ui.menuSettings)
        self._add_opts_to_menu(style_menu, \
          self.plotter.availStyles(), self.set_graph_style)
        self.ui.actionGraph_Style.setMenu(style_menu)

        #set up the list of files in the current directory
        self.directory = self.getPref('Default.FILE_DIRECTORY')

        file_db = AstonFileDatabase(op.join(self.directory, 'aston.sqlite'))
        self.obj_tab = FileTreeModel(file_db, self.ui.fileTreeView, self)
        self.plotData()

        #set up the compound database
        cmpd_db = AstonDatabase(self.getPref('Default.COMPOUND_DB'))
        self.cmpd_tab = FileTreeModel(cmpd_db, self.ui.compoundTreeView, self)

    def _add_opts_to_menu(self, menu, opts, fxn):
        menu_gp = QtGui.QActionGroup(self)
        for opt in opts:
            act = menu.addAction(opt, fxn)
            act.setData(opt)
            act.setCheckable(True)
            if opts.index(opt) == 0:
                act.setChecked(True)
            menu_gp.addAction(act)
        pass

    def updateWindows(self):
        """
        Update the tab windows to match the menu.
        """
        self.ui.filesDockWidget.setVisible(self.ui.actionFiles.isChecked())
        self.ui.settingsDockWidget.setVisible(self.ui.actionSettings.isChecked())
        self.ui.spectraDockWidget.setVisible(self.ui.actionSpectra.isChecked())
        self.ui.methodDockWidget.setVisible(self.ui.actionMethods.isChecked())
        self.ui.compoundDockWidget.setVisible(self.ui.actionCompounds.isChecked())

    def updateWindowsMenu(self):
        """
        Update the windows menu to match the tab.
        """
        self.ui.actionFiles.setChecked(self.ui.filesDockWidget.isVisible())
        self.ui.actionSettings.setChecked(self.ui.settingsDockWidget.isVisible())
        self.ui.actionSpectra.setChecked(self.ui.spectraDockWidget.isVisible())
        self.ui.actionMethods.setChecked(self.ui.methodDockWidget.isVisible())
        self.ui.actionCompounds.setChecked(self.ui.compoundDockWidget.isVisible())

    def getPref(self, key):
        try:
            import configparser
            cp = configparser.SafeConfigParser()
        except:
            import ConfigParser
            cp = ConfigParser.SafeConfigParser()
        cp.read('./settings.ini')
        try:
            return cp.get(key.split('.')[0], key.split('.')[1])
        except:
            return ''

    def openFolder(self):
        folder = str(QtGui.QFileDialog.getExistingDirectory(self, "Open Folder"))
        if folder == '':
            return
        self.directory = folder

        #need to discard old connections
        self.ui.fileTreeView.clicked.disconnect()
        self.ui.fileTreeView.customContextMenuRequested.disconnect()
        self.ui.fileTreeView.header().customContextMenuRequested.disconnect()
        self.ui.fileTreeView.header().sectionMoved.disconnect()

        #load everything
        file_db = AstonFileDatabase(op.join(self.directory, 'aston.sqlite'))
        self.obj_tab = FileTreeModel(file_db, self.ui.fileTreeView, self)
        self.plotData()

    def set_color_scheme(self):
        self.plotter.setColorScheme(self.sender().data())
        self.plotData()

    def set_legend(self):
        self.plotter.legend = self.ui.actionLegend.isChecked()
        self.plotData()

    def set_graph_style(self):
        self.plotter.style = str(self.sender().data()).lower()
        self.plotData()

    def exportSpectrumAsCSV(self):
        #FIXME: obsolete, needs to be integrated into exportSpectrum
        fname = str(QtGui.QFileDialog.getSaveFileName(self, "Save As..."))
        f = open(fname, 'w')
        cgrm = self.obj_tab.returnSelFile()
        scan = cgrm.scan(self.spec_line.get_xdata()[0])
        mz, abun = scan.keys(), scan.values()
        a = [['mz', 'abun']]
        a += zip([str(i) for i in mz], [str(i) for i in abun])
        for i in a:
            f.write(','.join(i) + '\n')
        f.close()

    def exportChromatogram(self):
        fname = str(QtGui.QFileDialog.getSaveFileName(self, "Save As..."))
        if fname[-4:].lower() == '.csv':
            #TODO: fix exporting chromatograms as CSV
            dt = self.obj_tab.active_file()
            f = open(fname, 'w')
            a = [['"Time"'] + [str(i) for i in dt.time()]]
            for ion in dt.info['traces'].split(','):
                if ion != '':
                    a += [['"' + ion + '"'] + [str(i) for ion in dt.trace(ion)]]
            for i in zip(*a):
                f.write(','.join(i) + '\n')
            f.close()
            pass
        else:
            self.plotter.plt.get_figure().savefig(fname, transparent=True)

    def exportSpectrum(self):
        fname = str(QtGui.QFileDialog.getSaveFileName(self, "Save As..."))
        self.specplotter.plt.get_figure().savefig(fname, transparent=True)

    def exportItems(self):
        #TODO: options for exporting different delimiters (e.g. tab) or
        #exporting select items as pictures (e.g. selected spectra)
        fname = str(QtGui.QFileDialog.getSaveFileName(self, "Save As..."))
        f = open(fname, 'w')
        sel = self.obj_tab.returnSelFiles()
        f.write(self.obj_tab.itemsAsCSV(sel))
        f.close()

    def quickIntegrate(self):
        #TODO: group peaks by time
        dt = self.obj_tab.active_file()
        ions = [i for i in dt.info['traces'].split(',')]

        #add compounds for ions from the first set
        for ion in ions:
            #pks = waveletIntegrate(dt, ion)
            pks = statSlopeIntegrate(dt, ion)
            self.obj_tab.addObjects(dt, pks)
        dt.info.del_items('s-peaks')
        self.plotter.redraw()

    def showFilterWindow(self):
        if self.obj_tab.returnSelFile() is not None:
            self.dlg = FilterWindow(self)
            self.dlg.show()

    def revertChromChange(self):
        """
        Delete all of the info keys related to display transformations.
        """
        for dt in self.obj_tab.returnSelFiles('file'):
            dt.info.del_items('t-')
        self.plotData()

    def plotData(self, **kwargs):
        datafiles = self.obj_tab.returnChkFiles()

        if 'updateBounds' in kwargs:
            self.plotter.plotData(datafiles, kwargs['updateBounds'])
        else:
            self.plotter.plotData(datafiles)

        # add all the peaks
        pks = []
        for dt in datafiles:
            pks += dt.getAllChildren('peak')
        self.plotter.add_peaks(pks)

    def updateSearch(self, text):
        """
        If the search box changes, update the file table.
        """
        self.obj_tab.proxyMod.setFilterFixedString(text)
