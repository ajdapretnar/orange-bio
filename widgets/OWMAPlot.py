"""<name>MA Plot</name>
<description>Normalize expression array data on a MA - plot</description>
<icon>icons/Normalize.png</icons>
"""

from OWWidget import *
from OWGraph import *
import OWGUI
import numpy

import obiExpression
        
import OWConcurrent
        
class OWMAPlot(OWWidget):
    settingsList = []
    contextHandlers = {"": DomainContextHandler("", ["selectedGroup", "selectedCenterMethod",
                                                     "selectedMergeMethod", "zCutoff"])}
    
    CENTER_METHODS = [("Average", obiExpression.MA_center_average),
                      ("Lowess (fast - interpolated)", obiExpression.MA_center_lowess_fast),
                      ("Lowess", obiExpression.MA_center_lowess)]
    
    MERGE_METHODS = [("Average", numpy.ma.average),
                     ("Median", numpy.ma.median)]
    
    def __init__(self, parent=None, signalManager=None, name="Normalize Expression Array"):
        OWWidget.__init__(self, parent, signalManager, name, wantGraph=True)
        
        self.inputs = [("Expression array", ExampleTable, self.setData)]
        self.outputs = [("Normalized expression array", ExampleTable), ("Filtered expression array", ExampleTable)]
        
        self.selectedGroup = 0
        self.selectedCenterMethod = 0
        self.selectedMergeMethod = 0
        self.zCutoff = 1.96
        self.appendZScore = False
        self.autoCommit = False
        
        self.loadSettings()
        ## GUI
        self.infoBox = OWGUI.widgetLabel(OWGUI.widgetBox(self.controlArea, "Info", addSpace=True),
                                         "No data on input.")
        
        box = OWGUI.widgetBox(self.controlArea, "Split by", addSpace=True)
        self.groupCombo = OWGUI.comboBox(box, self, "selectedGroup", 
                                         callback=self.onGroupSelection
                                         )
        
        self.centerCombo = OWGUI.comboBox(self.controlArea, self, "selectedCenterMethod",
                                          box="Center Fold-change Using",
                                          items=[name for name, _ in self.CENTER_METHODS],
                                          callback=self.onCenterMethodChange,
                                          addSpace=True
                                          )
        
        self.mergeCombo = OWGUI.comboBox(self.controlArea, self, "selectedMergeMethod",
                                         box="Merge Replicates",
                                         items=[name for name, _ in self.MERGE_METHODS],
                                         tooltip="Select the method for replicate merging",
                                         callback=self.onMergeMethodChange,
                                         addSpace=True
                                         )
        
        box = OWGUI.doubleSpin(self.controlArea, self, "zCutoff", 0.0, 3.0, 0.01,
                               box="Z-Score Cutoff",
                               callback=[self.replotMA, self.commitIf])
        
        OWGUI.separator(self.controlArea)
        
        box = OWGUI.widgetBox(self.controlArea, "Ouput")
        OWGUI.checkBox(box, self, "appendZScore", "Append Z-Scores",
                       tooltip="Append calculated Z-Scores to output",
                       callback=self.commit
                       )
        
        cb = OWGUI.checkBox(box, self, "autoCommit", "Commit on change",
                       tooltip="Commit data on any change",
                       callback=self.commitIf
                       )
        
        b = OWGUI.button(box, self, "Commit", callback=self.commit)
        OWGUI.setStopper(self, b, cb, "changedFlag", callback=self.commit)
        
        self.connect(self.graphButton, SIGNAL("clicked()"), self.saveGraph)
        
        OWGUI.rubber(self.controlArea)
        self.graph = OWGraph(self.mainArea)
        self.graph.setAxisTitle(QwtPlot.xBottom, "Intensity: log<sub>10</sub>(R*G)")
        self.graph.setAxisTitle(QwtPlot.yLeft, "Log ratio: log<sub>2</sub>(R/G)")
        self.mainArea.layout().addWidget(self.graph)
        self.groups = []
        self.split_data = None, None
        self.merged_splits = None, None
        self.changedFlag = False
        
        self.resize(800, 600)
        
#        self.myThread = WorkerThread()
#        self.myThread.start()
#        self.__thread = self.thread()
    
        
#    def createTask(self, call, args=(), kwargs={}, onResult=None):
#        async = QtAsyncCall(call, self.myThread)
#        self.connect(async, SIGNAL("resultReady(PyQt_PyObject)"), onResult, Qt.QueuedConnection)
#        self.connect(async, SIGNAL("finished(QString)"), self.onFinished, Qt.QueuedConnection)
#        self.connect(async, SIGNAL("unhandledException(PyQt_PyObject)"), self.onUnhandledException, Qt.QueuedConnection)
#        async(*args, **kwargs)
#        self.setEnabled(False)
#        return async
    
        
    def onFinished(self, status):
        self.setEnabled(True)
    
    
    def onUnhandledException(self, ex_info):
        print >> sys.stderr, "Unhandled exception in non GUI thread"
        
        ex_type, ex_val, tb = ex_info
        if ex_type == numpy.linalg.LinAlgError:
            self.error(0, "Linear algebra error: %s" % repr(ex_val))
        else:
            sys.excepthook(*ex_info)
    
    
    def onGroupSelection(self):
        self.splitData()
        self.runNormalization()
        
        
    def onCenterMethodChange(self):
        self.runNormalization()
        
        
    def onMergeMethodChange(self):
        self.splitData()
        self.runNormalization()
        
        
    def setData(self, data):
        self.closeContext("")
        self.data = data
        self.error(0)
        if data is not None:
            self.infoBox.setText("%i genes on input" % len(data))
            groups = [attr.attributes.keys() for attr in data.domain.attributes]
            self.groups = sorted(reduce(set.union, groups, set()))
            all_labels = [attr.attributes.items() for attr in data.domain.attributes]
            self.all_labels = reduce(set.union, all_labels, set())
            self.groupCombo.clear()
            self.groupCombo.addItems(["%s" % group for group in self.groups])
            self.selectedGroup = min(self.selectedGroup, len(self.groups) - 1)
            self.openContext("", data)
            self.splitData()
            self.runNormalization()
        else:
            self.clear()
        
        
    def clear(self):
        self.groups = []
        self.split_data = None, None
        self.merged_splits = None, None
        
        
    def getLabelGroups(self):
        group = self.groups[self.selectedGroup]
        labels = [label for key, label in self.all_labels if key==group]
        if len(labels) != 2:
            raise ValueError("Group %s has more or less labels then 2" % group)
        
        label1, label2 = labels
        return [(group, label1), (group, label2)]
        
        
    def splitData(self):
        label_groups = self.getLabelGroups()
        self.split_ind = obiExpression.attr_group_indices(self.data, label_groups)
        self.split_data = obiExpression.data_group_split(self.data, label_groups)
        
        
    def getMerged(self):
        split1, split2 = self.split_data
        (array1, _, _), (array2, _, _) = split1.toNumpyMA(), split2.toNumpyMA()
        merge_function = self.MERGE_METHODS[self.selectedMergeMethod][1]
        merged1 = obiExpression.merge_replicates(array1, 1, merge_function=merge_function)
        merged2 = obiExpression.merge_replicates(array2, 1, merge_function=merge_function)
        
        self.merged_splits = merged1, merged2
        
        return self.merged_splits
        
        
    def runNormalization(self):
        self.progressBarInit()
        self.progressBarSet(0.0)
        G, R = self.getMerged()
        self.progressBarSet(5.0)
        
        center_method = self.CENTER_METHODS[self.selectedCenterMethod][1]
        if center_method == obiExpression.MA_center_lowess:
            pass # set the lowess window

        # TODO: progess bar , lowess can take a long time
        if self.selectedCenterMethod in [1, 2]: #Lowess
            Gc, Rc = center_method(G, R, f = 1./min(500., len(G)/100), iter=1)
        else:
            Gc, Rc = center_method(G, R)
        self.progressBarSet(70.0)
        self.centered = Gc, Rc
        self.z_scores = obiExpression.MA_zscore(Gc, Rc, 1./3.)
        self.progressBarSet(100.0)
        self.plotMA(Gc, Rc, self.z_scores, self.zCutoff)
        self.progressBarFinished()
        
        
    def runNormalizationAsync(self):
        """ Run MA centering and z_score estimation in a separate thread 
        """
        self.setEnabled(False)
        self.error(0)
        self.progressBarInit()
        self.progressBarSet(0.0)
        G, R = self.getMerged()
        self.progressBarSet(5.0)
        
        center_method = self.CENTER_METHODS[self.selectedCenterMethod][1]
        
        if center_method == obiExpression.MA_center_lowess:
            pass # set the lowess window
        
        def onCenterResult((Gc, Rc)):
            """ Handle results of MA_center* method
            """
            self.centered = Gc, Rc
            self.progressBarSet(70.0)
            def onZScores(z_scores):
                """ Handle results of MA_z_scores method
                """
                self.z_scores = z_scores
                self.progressBarFinished()
                self.setEnabled(True)
                QTimer.singleShot(50, lambda: self.plotMA(Gc, Rc, self.z_scores, self.zCutoff))
                
            self.z_scores_async = OWConcurrent.createTask(obiExpression.MA_zscore, (Gc, Rc, 1./3.),
                                                          onResult=onZScores,
                                                          onError=self.onUnhandledException)
            
        if self.selectedCenterMethod in [1, 2]: #Lowess
            async_center = OWConcurrent.createTask(center_method, (G, R), {"f": 1./min(500., len(G)/100),
                                                                           "iter": 1},
                                                   onResult=onCenterResult,
                                                   onError=self.onUnhandledException)
        else:
            async_center = OWConcurrent.createTask(center_method, (G, R),
                                                   onResult=onCenterResult,
                                                   onError=self.onUnhandledException)

        self.async_center = async_center
            
    ## comment out this line if threading creates any problems 
    runNormalization = runNormalizationAsync
    
    
    def plotMA(self, G, R, z_scores, z_cuttof):
        ratio, intensity = obiExpression.ratio_intensity(G, R)
        
        filter = numpy.isfinite(ratio) & numpy.isfinite(intensity) & numpy.isfinite(z_scores)
        for array in [ratio, intensity, z_scores]:
            if numpy.ma.is_masked(array):
                filter &= array != numpy.ma.masked
        
        filtered_ind = numpy.where(filter)
        ratio = numpy.take(ratio, filtered_ind)
        intensity = numpy.take(intensity, filtered_ind)
        z_scores = numpy.take(z_scores, filtered_ind)
        
        red_ind = numpy.where(numpy.ma.abs(z_scores) >= z_cuttof)
        blue_ind = numpy.where(numpy.ma.abs(z_scores) < z_cuttof)
        
        red_xdata, red_ydata = intensity[red_ind], ratio[red_ind]
        blue_xdata, blue_ydata = intensity[blue_ind], ratio[blue_ind]
        self.graph.removeDrawingCurves()
#        print ratio, intensity
        c = self.graph.addCurve("", Qt.black, Qt.black, xData=[0.0, 1.0], yData=[0.0, 0.0], style=QwtPlotCurve.Lines, symbol=QwtSymbol.NoSymbol)
        c.setAxis(QwtPlot.xTop, QwtPlot.yLeft)
        
        self.graph.addCurve("Z >= %.2f" % z_cuttof, Qt.red, Qt.red, enableLegend=True, xData=list(red_xdata), yData=list(red_ydata), autoScale=True)
        self.graph.addCurve("Z < %.2f" % z_cuttof, Qt.blue, Qt.blue, enableLegend=True, xData=list(blue_xdata), yData=list(blue_ydata), autoScale=True)
        
        self.graph.setAxisScale(QwtPlot.xTop, 0.0, 1.0)
        
        self.graph.replot()
        
        
    def replotMA(self):
        Gc, Rc = self.centered
        self.plotMA(Gc, Rc, self.z_scores, self.zCutoff)
        
        
    def commitIf(self):
        if self.autoCommit and self.changedFlag:
            self.commit()
        else:
            self.changedFlag = True
            
            
    def commit(self):
        G, R = self.merged_splits
        Gc, Rc = self.centered
        ind1, ind2 = self.split_ind
        
        gfactor = Gc / G
        
        domain = orange.Domain(self.data.domain.attributes, self.data.domain.classVar)
        domain.addmetas(self.data.domain.getmetas())
        if self.appendZScore:
            attr = orange.FloatVariable("Z-Score")
            if not hasattr(self, "z_score_mid"):
                self.z_score_mid = orange.newmetaid()
            mid = self.z_score_mid
            domain.addmeta(mid, attr)
            
        data = orange.ExampleTable(domain, self.data)
            
        for ex, gf, z in zip(data, gfactor, self.z_scores):
            for i in ind1:
                if not ex[i].isSpecial():
                    ex[i] = float(ex[i]) * gf
            if self.appendZScore:
                ex[attr] = z
            
        self.z_scores
        filtered_ind = list(numpy.ma.abs(self.z_scores) >= self.zCutoff)
        filtered_data = data.select([int(b) for b in filtered_ind])
        self.send("Normalized expression array", data)
        self.send("Filtered expression array", filtered_data)
        
        
    def saveGraph(self):
        from OWDlgs import OWChooseImageSizeDlg
        dlg = OWChooseImageSizeDlg(self.graph, parent=self)
        dlg.exec_()
        
        
if __name__ == "__main__":
    app = QApplication(sys.argv)
    w= OWMAPlot()
    data = orange.ExampleTable(os.path.expanduser("~/GDS1210.tab"))
    w.setData(data)
    w.show()
    app.exec_()
        
        