# Copyright (c) 2013 Shotgun Software Inc.
# 
# CONFIDENTIAL AND PROPRIETARY
# 
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit 
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your 
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights 
# not expressly granted therein are reserved by Shotgun Software Inc.

import tank
from tank import TankError
import os
import sys
import threading

from tank.platform.qt import QtCore, QtGui

from .entitymodel import SgEntityModel
from .publishmodel import SgPublishModel
from .publishtypemodel import SgPublishTypeModel
from .publishproxymodel import SgPublishProxyModel 
from .publishdelegate import SgPublishDelegate
from .detailshandler import DetailsHandler
from .shotgunmodel import ShotgunModel

from .ui.dialog import Ui_Dialog

class EntityPreset(object):
        
    def __init__(self, name, entity_type, model, view):
        
        self.model = model
        self.name = name
        self.view = view
        self.entity_type = entity_type 
        

class AppDialog(QtGui.QWidget):

    def _restart(self):
        tank.platform.restart()
        tank.platform.current_engine().commands["Show me the new Loader!"]["callback"]()

    def __init__(self):
        QtGui.QWidget.__init__(self)
        
        # set up the UI
        self.ui = Ui_Dialog()
        self.ui.setupUi(self)
        
        #################################################
        # maintain a list where we keep a reference to
        # all the dynamic UI we create. This is to make
        # the GC happy.
        self._dynamic_widgets = []
        
        # flag to indicate that the current selection 
        # operation is part of a programatic selection
        # and not a generated by a user clicking
        self._programmatic_selection_mode = False 
        
        # temp -- todo: remove
        self.ui.reload.clicked.connect(self._restart)
        
        #################################################
        # details pane mockup for now
        self.ui.details.setVisible(False)
        self.ui.info.toggled.connect(self._on_info_toggled)
        
        # thumb scaling
        self.ui.thumb_scale.valueChanged.connect(self._on_thumb_size_slider_change)
        self.ui.thumb_scale.setValue(140)
        
        #################################################
        # details pane
        self._details_handler = DetailsHandler(self.ui)
        
        #################################################
        # load and initialize cached publish type model
        self._publish_type_model = SgPublishTypeModel(self.ui.publish_type_list)        
        self.ui.publish_type_list.setModel(self._publish_type_model)

        #################################################
        # setup publish model
        self._publish_model = SgPublishModel(self.ui.publish_list, self._publish_type_model)
        
        # set up a proxy model to cull results based on type selection
        self._publish_proxy_model = SgPublishProxyModel(self)
        self._publish_proxy_model.setSourceModel(self._publish_model)
                
        # tell our publish view to use a custom delegate to produce widgetry
        #self._publish_delegate = SgPublishDelegate(self.ui.publish_list, self) 
        #self.ui.publish_list.setItemDelegate(self._publish_delegate)
                
        # hook up view -> proxy model -> model
        self.ui.publish_list.setModel(self._publish_proxy_model)
        
        # whenever the type list is checked, update the publish filters
        self._publish_type_model.itemChanged.connect(self._apply_type_filters_on_publishes)        
        
        # if an item in the table is double clicked ensure details are shown
        self.ui.publish_list.doubleClicked.connect(self._on_publish_double_clicked)
        
        # event handler for when the selection in the publish view is changing
        self.ui.publish_list.selectionModel().selectionChanged.connect(self._on_publish_selection)
        
        #################################################
        # setup history
        
        self._history = []
        self._history_index = 0
        # state flag used by history tracker to indicate that the 
        # current navigation operation is happen as a part of a 
        # back/forward operation and not part of a user's click
        self._history_navigation_mode = False
        self.ui.navigation_home.clicked.connect(self._on_home_clicked)
        self.ui.navigation_prev.clicked.connect(self._on_back_clicked)
        self.ui.navigation_next.clicked.connect(self._on_forward_clicked)
        
        #################################################
        # set up preset tabs and load and init tree views
        self._entity_presets = {} 
        self._current_entity_preset = None
        self._load_entity_presets()
        
        # lastly, set the splitter ratio roughly. QT will do fine adjustments.
        self.ui.left_side_splitter.setSizes( [400, 200] )
        
        
    
    def closeEvent(self, event):
        
        self._publish_model.destroy()
        self._details_handler.destroy()
        self._publish_type_model.destroy()
        for p in self._entity_presets:
            self._entity_presets[p].model.destroy()
        
        # okay to close!
        event.accept()
                
    ########################################################################################
    # info bar related
    
    def _on_info_toggled(self, checked):
        if checked:
            self.ui.details.setVisible(True)
            
            # if there is something selected, make sure the detail
            # section is focused on this 
            selection_model = self.ui.publish_list.selectionModel()     
            
            if selection_model.hasSelection():
            
                current_proxy_model_idx = selection_model.selection().indexes()[0]
                
                # the incoming model index is an index into our proxy model
                # before continuing, translate it to an index into the 
                # underlying model
                proxy_model = current_proxy_model_idx.model()
                source_index = proxy_model.mapToSource(current_proxy_model_idx)
                
                # now we have arrived at our model derived from StandardItemModel
                # so let's retrieve the standarditem object associated with the index
                item = source_index.model().itemFromIndex(source_index)
            
                self._details_handler.load_details(item)
            
            else:
                self._details_handler.clear()
            
            
        else:
            self.ui.details.setVisible(False)
        
        
    ########################################################################################
    # history related
    
    def _compute_history_button_visibility(self):
        """
        compute history button enabled/disabled state based on contents of history stack.
        """
        self.ui.navigation_next.setEnabled(True)
        self.ui.navigation_prev.setEnabled(True)
        if self._history_index == len(self._history):
            self.ui.navigation_next.setEnabled(False) 
        if self._history_index == 1:
            self.ui.navigation_prev.setEnabled(False)         
    
    def _add_history_record(self, preset_caption, std_item):
        """
        Adds a record to the history stack
        """
        # self._history_index is a one based index that points at the currently displayed
        # item. If it is not pointing at the last element, it means a user has stepped back
        # in that case, discard the history after the current item and add this new record
        # after the current item

        if not self._history_navigation_mode: # do not add to history when browsing the history :)
            self._history = self._history[:self._history_index]         
            self._history.append({"preset": preset_caption, "item": std_item})
            self._history_index += 1

        # now compute buttons
        self._compute_history_button_visibility()
        
    def _history_navigate_to_item(self, preset, item):
        """
        Focus in on an item in the tree view.
        """
        # tell rest of event handlers etc that this navigation
        # is part of a history click. This will ensure that no
        # *new* entries are added to the history log when we 
        # are clicking back/next...
        self._history_navigation_mode = True
        try:            
            self._select_item_in_entity_tree(preset, item)            
        finally:
            self._history_navigation_mode = False
        
    def _on_home_clicked(self):
        """
        User clicks the home button
        """
        # first, try to find the "home" item by looking at the current app context.
        found_profile = None
        found_item = None
        
        # get entity portion of context
        ctx = tank.platform.current_bundle().context
        if ctx.entity:

            # now step through the profiles and find a matching entity
            for p in self._entity_presets:
                if self._entity_presets[p].entity_type == ctx.entity["type"]:
                    # found an at least partially matching entity profile.
                    found_profile = p
                                        
                    # now see if our context object also exists in the tree of this profile
                    model = self._entity_presets[p].model
                    item = model.item_from_entity(ctx.entity["type"], ctx.entity["id"]) 
                    
                    if item is not None:
                        # find an absolute match! Break the search.
                        found_item = item
                        break
                
        if found_profile is None:
            # no suitable item found. Use the first tab
            found_profile = self.ui.entity_preset_tabs.tabText(0)
            
        # select it in the list
        self._select_item_in_entity_tree(found_profile, found_item)
                
    def _on_back_clicked(self):
        """
        User clicks the back button
        """
        self._history_index += -1
        # get the data for this guy (note: index are one based)
        d = self._history[ self._history_index - 1]
        self._history_navigate_to_item(d["preset"], d["item"])
        self._compute_history_button_visibility()
        
    def _on_forward_clicked(self):
        """
        User clicks the forward button
        """
        self._history_index += 1
        # get the data for this guy (note: index are one based)
        d = self._history[ self._history_index - 1]
        self._history_navigate_to_item(d["preset"], d["item"])
        self._compute_history_button_visibility()
        
    ########################################################################################
    # filter view
        
    def _apply_type_filters_on_publishes(self):
        """
        Executed when the type listing changes
        """         
        # go through and figure out which checkboxes are clicked and then
        # update the publish proxy model so that only items of that type 
        # is displayed
        sg_type_ids = self._publish_type_model.get_selected_types()
        self._publish_proxy_model.set_filter_by_type_ids(sg_type_ids)

    ########################################################################################
    # publish view
        
    def _on_thumb_size_slider_change(self, value):
        """
        When scale slider is manipulated
        """
        self.ui.publish_list.setIconSize(QtCore.QSize(value, value))
        
    def _on_publish_selection(self, selected, deselected):
        """
        Signal triggered when someone changes the selection in the main publish area
        """
        if self.ui.details.isVisible():
            # since we are controlling the details view, no need to do anything if
            # it is not visible
        
            selected_indexes = selected.indexes()
            
            if len(selected_indexes) == 0:
                # get
                self._details_handler.clear()
                
            else:
                # get the currently selected model index
                model_index = selected_indexes[0]
        
                # the incoming model index is an index into our proxy model
                # before continuing, translate it to an index into the 
                # underlying model
                proxy_model = model_index.model()
                source_index = proxy_model.mapToSource(model_index)
                
                # now we have arrived at our model derived from StandardItemModel
                # so let's retrieve the standarditem object associated with the index
                item = source_index.model().itemFromIndex(source_index)
                
                # tell details pane to load stuff
                self._details_handler.load_details(item)
        
        
        
    def _on_publish_double_clicked(self, model_index):
        """
        When someone double clicks an item in the publish area,
        ensure that the details pane is visible
        """
        
        # the incoming model index is an index into our proxy model
        # before continuing, translate it to an index into the 
        # underlying model
        proxy_model = model_index.model()
        source_index = proxy_model.mapToSource(model_index)
        
        # now we have arrived at our model derived from StandardItemModel
        # so let's retrieve the standarditem object associated with the index
        item = source_index.model().itemFromIndex(source_index)
        
        is_folder = item.data(SgPublishModel.IS_FOLDER_ROLE)
        
        if is_folder:
            
            # get the corresponding tree view item
            tree_view_item = item.data(SgPublishModel.ASSOCIATED_TREE_VIEW_ITEM_ROLE)
            
            # select it in the tree view
            self._select_item_in_entity_tree(self._current_entity_preset, tree_view_item)
            
        else:
            # ensure publish details are visible
            if not self.ui.info.isChecked():
                self.ui.info.setChecked(True)
        
    ########################################################################################
    # entity listing tree view and presets toolbar
        
    def _select_item_in_entity_tree(self, tab_caption, item):
        """
        Select an item in the entity tree, ensure the tab
        which holds it is selected and scroll to make it visible.
        
        Item can be None - in this case, nothing is selected.
        """
        
        # indicate that all events triggered by operations in here
        # originated from this programmatric request and not by
        # a user's click
        self._programmatic_selection_mode = True
        
        try:
            # set the right tab
            if tab_caption != self._current_entity_preset:            
                for idx in range(self.ui.entity_preset_tabs.count()):
                    tab_name = self.ui.entity_preset_tabs.tabText(idx)
                    if tab_name == tab_caption:
                        # click the tab view control. This will call the 
                        # on-index changed events, shift the new content
                        # into view and prepare the treeview.
                        self.ui.entity_preset_tabs.setCurrentIndex(idx)
            
            
            # now focus on the item
            view = self._entity_presets[self._current_entity_preset].view
            selection_model = view.selectionModel()

            if item:
                # ensure that the tree view is expanded and that the item we are about 
                # to selected is in vertically centered in the widget
                view.scrollTo(item.index(), QtGui.QAbstractItemView.PositionAtCenter)
            
                selection_model.select(item.index(), QtGui.QItemSelectionModel.ClearAndSelect)
                selection_model.setCurrentIndex(item.index(), QtGui.QItemSelectionModel.ClearAndSelect)
                
            else:
                # clear selection to match none item
                selection_model.clear()
                                
            # note: the on-select event handler will take over at this point and register
            # history, handle click logic etc.
            
        finally:
            self._programmatic_selection_mode = False
        
    def _load_entity_presets(self):
        """
        Loads the entity presets from the configuration and sets up buttons and models
        based on the config.
        """
        app = tank.platform.current_bundle()
        entities = app.get_setting("entities")
        
        for e in entities:
            
            # validate that the settings dict contains all items needed.
            for k in ["caption", "entity_type", "hierarchy", "filters"]:
                if k not in e:
                    raise TankError("Configuration error: One or more items in %s "
                                    "are missing a '%s' key!" % (entities, k))
        
            # set up a bunch of stuff
            
            # resolve any magic tokens in the filter
            resolved_filters = []
            for filter in e["filters"]:
                resolved_filter = []
                for field in filter:
                    if field == "{context.entity}":
                        field = app.context.entity
                    elif field == "{context.project}":
                        field = app.context.project
                    elif field == "{context.step}":
                        field = app.context.step
                    elif field == "{context.task}":
                        field = app.context.task
                    elif field == "{context.user}":
                        field = app.context.user                    
                    resolved_filter.append(field)
                resolved_filters.append(resolved_filter)
            e["filters"] = resolved_filters
            
            
            preset_name = e["caption"]
            sg_entity_type = e["entity_type"]
            
                        
            # now set up a new tab
            tab = QtGui.QWidget()
            # add a layout
            layout = QtGui.QVBoxLayout(tab)
            layout.setSpacing(1)
            layout.setContentsMargins(1, 1, 1, 1)
            # and add a treeview
            view = QtGui.QTreeView(tab)
            layout.addWidget(view)
            # add it to the main tab UI
            self.ui.entity_preset_tabs.addTab(tab, preset_name)

            # make sure we keep a handle to all the new objects
            # otherwise the GC may not work
            self._dynamic_widgets.extend( [tab, layout, view] )

            # set up data backend
            model = SgEntityModel(view)
            # set up and load up from cache if possible
            model.load_data(sg_entity_type, 
                            e["filters"], 
                            e["hierarchy"],
                            fields=[],
                            order=[])

            # configure the view
            view.setEditTriggers(QtGui.QAbstractItemView.NoEditTriggers)
            view.setProperty("showDropIndicator", False)
            view.setIconSize(QtCore.QSize(16, 16))
            view.setHeaderHidden(True)
            view.setModel(model)
            # expand first level of items 
            view.expandToDepth(0)
        
            # set up on-select callbacks
            selection_model = view.selectionModel()
            selection_model.selectionChanged.connect(self._on_treeview_item_selected)
            
            # finally store all these objects keyed by the caption
            ep = EntityPreset(preset_name,
                              sg_entity_type,
                              model,
                              view)
            
            self._entity_presets[preset_name] = ep
            
        # hook up an event handler when someone clicks a tab
        self.ui.entity_preset_tabs.currentChanged.connect(self._on_entity_profile_tab_clicked)
                
        # finalize initialization by clicking the home button, but only once the 
        # data has properly arrived in the model. empty_refresh_completed
        
        self._on_home_clicked()
        
    def _on_entity_profile_tab_clicked(self):
        """
        Called when someone clicks one of the profile tabs
        """
        # get the name of the clicked tab        
        curr_tab_index = self.ui.entity_preset_tabs.currentIndex()
        curr_tab_name = self.ui.entity_preset_tabs.tabText(curr_tab_index)

        # and set up which our currently visible preset is
        self._current_entity_preset = curr_tab_name 
                
        if self._history_navigation_mode == False:
            # when we are not navigating back and forth as part of 
            # history navigation, ask the currently visible
            # view to (background async) refresh its data
            model = self._entity_presets[self._current_entity_preset].model
            model.refresh_data()
        
        if self._programmatic_selection_mode == False:
            # this request is because a user clicked a tab
            # and not part of a history operation (or other)

            # programmatic selection means the operation is part of a
            # combo selection process, where a tab is first selection
            # and then an item. So in this case we should not 
            # register history or trigger a refresh of the publish
            # model, since these operations will be handled by later
            # parts of the combo operation

            # now figure out what is selected            
            selected_item = None
            selection_model = self._entity_presets[self._current_entity_preset].view.selectionModel()
            if selection_model.hasSelection():
                # get the current index
                current = selection_model.selection().indexes()[0]
                # get selected item
                selected_item = current.model().itemFromIndex(current)
            
            # add history record
            self._add_history_record(self._current_entity_preset, selected_item)
            
            # finally, tell the publish view to change 
            self._load_publishes_for_entity_item(selected_item)
        
        
    def _on_treeview_item_selected(self):
        """
        Signal triggered when someone changes the selection in a treeview.
        """

        # update breadcrumbs
        self._populate_entity_breadcrumbs()
        
        selection_model = self._entity_presets[self._current_entity_preset].view.selectionModel()
        
        item = None
        
        if selection_model.hasSelection():            
            # get the current index
            current = selection_model.selection().indexes()[0]
            # get selected item
            item = current.model().itemFromIndex(current)
        
        # notify history
        self._add_history_record(self._current_entity_preset, item)
        
        # tell publish UI to update itself
        self._load_publishes_for_entity_item(item)
            
    
    def _load_publishes_for_entity_item(self, item):
        """
        Given an item from the treeview, or None if no item
        is selected, prepare the publish area UI.
        """
        child_folders = []
        sg_data = None
        
        if item:
            # get sg data for this item so we can pass it to the publish model
            sg_data = item.data(ShotgunModel.SG_DATA_ROLE)
            
            # and get all the folder children - these need to be displayed
            # by the model as folders
            for child_idx in range(item.rowCount()):
                child_folders.append(item.child(child_idx))
            
        # load publishes
        print "load data"
        self._publish_model.load_data(sg_data, child_folders)
        self._publish_model.refresh_data()
            

    def _populate_entity_breadcrumbs(self):
        """
        Computes the current entity breadcrumbs
        """
        
        selection_model = self._entity_presets[self._current_entity_preset].view.selectionModel()
        
        crumbs = []
    
        if selection_model.hasSelection():
        
            # get the current index
            current = selection_model.selection().indexes()[0]
            # get selected item
            item = current.model().itemFromIndex(current)
            
            # figure out the tree view selection, 
            # walk up to root, list of items will be in bottom-up order...
            tmp_item = item
            while tmp_item:
                crumbs.append(tmp_item.text())
                tmp_item = tmp_item.parent()
                    
        breadcrumbs = " > ".join( crumbs[::-1] )  
        self.ui.entity_breadcrumbs.setText("<big>%s</big>" % breadcrumbs)
        