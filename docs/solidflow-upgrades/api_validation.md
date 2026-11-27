# SOLIDWORKS API validation record (Phase 1 + Phase 2)

**Runtime probed:** SOLIDWORKS 2025 SP5, `RevisionNumber` = `33.5.0` (major 33), Windows 11, Student Edition (output PDFs carry the license watermark text
"SOLIDWORKS Educational Product. For Instructional Use Only." - a property of this install, not of the pipeline).
**Signature source:** the installed type library, read statically from the generated `gen_py` module (`SldWorks 2026 Type Library` is what Windows
registers on this machine; the 2025 runtime accepted every member below, which is the evidence that matters). `help.solidworks.com/2025/english/api/`
was **not browsed** (no web access from the worker); every member was instead proven by a minimal live call. The installed type library and the live call
are the final authority, as the architecture spec requires. No enum value below is guessed: each was read from the type library.

| Task | Member (as called) | Live result on 33.5.0 |
|---|---|---|
| Version | `ISldWorks.RevisionNumber` (property) | `"33.5.0"` -> major 33 = 2025, SP5 |
| Open part | `ISldWorks.OpenDoc6(path, swDocPART=1, swOpenDocOptions_Silent=1, "", 0, 0)` (typed; returns `(doc, errors, warnings)`) | opens; `ReadOnly(2)` is avoided (error log E025) |
| Document type | `IModelDoc2.GetType()` | 1 for a part |
| Configurations | `IModelDoc2.GetConfigurationNames()`, `ConfigurationManager.ActiveConfiguration.Name`, `ShowConfiguration2(name)` | works |
| Bodies / box | `IPartDoc.GetBodies2(0, False)` (**on IPartDoc, not IModelDoc2**), `IBody2.GetBodyBox()` | works |
| STL export | `IModelDoc2.SaveAs3(path, 0, 1)` with prefs `swSTLBinaryFormat=69`(toggle), `swExportStlUnits=211`(int, `swMM=0`), `swSTLQuality=78`(int, Fine=2), `swSTLShowInfoOnSave=70`, `swSTLDontTranslateToPositive=71` via `Get/SetUserPreferenceToggle/IntegerValue` | binary STL, 1666 triangles for the probe part, size equals the native body box to 0.0 %; prefs restored in `finally` |
| Feature walk | `IModelDoc2.FirstFeature()` (method on the typed object), `IFeature.Name/GetTypeName2()/GetNextFeature()` | works |
| B-rep faces | `IBody2.GetFaces()`, `IFace2.GetSurface()`, `ISurface.IsPlane/IsCylinder/IsCone/IsTorus`, `PlaneParams`, `CylinderParams` (origin, axis, radius), `IFace2.GetBox/GetArea/GetEdges/FaceInSurfaceSense` | a cylinder with `FaceInSurfaceSense == True` is a hole (face normal points at the axis); verified on 13 cylindrical faces |
| New drawing | `ISldWorks.NewDocument(template, swDwgPaperBsize=2, 0.4318, 0.2794)` | creates `Draw1 - Sheet1`; the drawing document is renamed by `SaveAs3` (re-read `GetTitle()` before `CloseDoc`) |
| Sheet setup | `IDrawingDoc.SetupSheet5(name, paper, swDwgTemplateNone=13, s1, s2, firstAngle, "", w, h, "Default", True)` | works; **does not change the scale of views created afterwards** - set `IView.ScaleDecimal` per view |
| Base view | `IDrawingDoc.CreateDrawViewFromModelView3(path, "*Front"/"*Top"/"*Right"/"*Bottom"/"*Isometric", x, y, 0)` | works; the view centre is `x, y` |
| Projected view | select the parent (`IModelDocExtension.SelectByID2(name, "DRAWINGVIEW", ...)`) then `IDrawingDoc.CreateUnfoldedViewAt3(x, y, 0, False)` | aligned third-angle views |
| View scale / place | `IView.ScaleDecimal = s`, `IView.Position = com_doubles(x, y)`, `IView.SetDisplayMode3(False, swViewDisplayMode_HiddenLinesRemoved=2, False, False)`, `IView.GetOutline()` | works; real outline is ~6.5 mm larger per side than the part (centre marks) |
| Edge enumeration | `IView.GetVisibleEntities2(None, swViewEntityType_Edge=1)`, `IEdge.GetCurve()`, `ICurve.IsLine/IsCircle`, `IEdge.GetCurveParams2()`, `ICurve.CircleParams` | works |
| Model -> sheet | `IView.ModelToViewTransform` + `IMathUtility.CreatePoint(com_doubles(x,y,z))` + `IMathPoint.MultiplyTransform` | works **only** with a typed double-array point (plain Python lists mis-marshal) |
| Select edge | `IEntity.Select4(append, None)` | True |
| Dimensions | `IModelDoc2.AddHorizontalDimension2/AddVerticalDimension2(x,y,0)` | native associative dimensions; circle-to-edge dimensions measure to the circle **centre** by default (`IDimension.GetArcEndCondition(1)==1`) |
| Hole callout | `IDrawingDoc.AddHoleCallout2(x, y, 0)` after selecting the circle edge | `Ø0.406 THRU`; blind holes carry their depth; multiplier via `IDisplayDimension.SetText(swDimensionTextPrefix=1, "4X <MOD-DIAM>")` |
| Value read-back | `IDisplayDimension.GetDimension2(0).SystemValue` (SI metres) | exact (e.g. 0.08255 m). `GetSystemValue3` returned `None` here and is not used |
| Precision | `IDisplayDimension.SetPrecision3(p,p,p,p)` per dimension | `0.406`, `2.375`; the document option `swDetailingLinearDimPrecision=24` did **not** take effect on its own |
| Black ink | `IDrawingDoc.CreateLayer2(name, desc, 0x000000, 0, 1, True, True)` + `SetCurrentLayer` | text and lines are black in the vector PDF (0 non-black spans or strokes) |
| Notes | `IModelDoc2.InsertNote(text)`, `INote.GetAnnotation()`, `IAnnotation.SetPosition2` | `ClearSelection2(True)` first, else the note grows a leader to the selection |
| Annotation import | `IDrawingDoc.InsertModelAnnotations3(0, 8\|64, True, False, False, True)` | returns nothing for API-built parts: their sketch dimensions are not marked for drawing. Geometry-derived dimensions are therefore generated |
| Save / PDF | `IModelDocExtension.SaveAs3(path, 0, 1, exportData, None, 0, 0)`; `ISldWorks.GetExportFileData(swExportPdfData=1)`; `IExportPdfData.SetSheets(swExportData_ExportAllSheets=1, None)` returns False but the default exports all sheets | SLDDRW + vector PDF written; page count equals `GetSheetCount()` |
| Reopen check | `OpenDoc6(slddrw, swDocDRAWING=3, ...)`, `GetFirstView/GetNextView`, `IView.GetReferencedModelName`, `GetDisplayDimensions` | views reference the part, dimensions survive |
| Sheet format | `ISheet.SaveFormat(path.slddrt)`, `IDrawingDoc.EditTemplate/EditSheet`, `IModelDoc2.CreateLine2` with `SketchManager.AddToDB = True` (exact coordinates; inference otherwise snaps lines) | native `.slddrt` + `.DRWDOT` written and re-validated |
| Title-block links | notes with `$PRP:"SF_*"`, `$PRP:"SW-Sheet Scale"`, `$PRP:"SW-Current Sheet"`, `$PRP:"SW-Total Sheets"`; drawing properties via `IModelDocExtension.CustomPropertyManager("").Add3(name, 30, value, 2)` | resolve in the PDF (`SCALE 1:1`, `SHEET 1 OF 1`); `$PRPSHEET:` does **not** resolve these |
| **Material (Phase 1)** | `IPartDoc.SetMaterialPropertyName2(config, database, name)`, `GetMaterialPropertyName2(config, "")` -> `(name, libraryDisplayName)` | needs the **active configuration's real name** (not `""`); read-back returns the library display name (`"SOLIDWORKS Materials"`, `"solidflow-demo"`), not a path |
| Material database folders | `ISldWorks.Get/SetUserPreferenceStringValue(swFileLocationsMaterialDatabases=28)` | a database outside a registered folder is silently ignored (even a byte-identical copy); the folder is registered temporarily and the original list restored |
| Mass properties | `IModelDocExtension.CreateMassProperty2()` -> `.Volume/.Mass/.Density/.SurfaceArea` | density follows the assigned material (7850, 8960, 1240 verified) |
| Custom properties | `IModelDocExtension.CustomPropertyManager(config).Add3(...)` | `SolidFlow_MaterialStatus/Source/DrawingText/Catalog` written (traceability only; never a substitute for the native assignment) |

## Gotchas found the hard way (each one has a fix in the code)
1. `GetBodies2` / `CreateMassProperty2` are not on `IModelDoc2`; use the typed `IPartDoc` / `IModelDocExtension`.
2. COM wrapper objects cannot carry extra Python attributes.
3. `SaveAs3` to `.drwdot` renames the open document; closing by the old title leaves it open and locks the file.
4. A note created while geometry is selected gets a leader.
5. Sketch inference moves new endpoints; build programmatic geometry with `AddToDB = True`.
6. A dimension is measured in the view plane: compare against model geometry projected into that plane (a counterbore floor sits 2.8 mm deeper than the part face).

## v7 drawing standards (SOLIDWORKS 2025 SP5, 33.5.0; verified live 2026-11-27 against sldworks.tlb / swconst.tlb)

| Need | API (verified) | Constant / readback | Evidence |
|---|---|---|---|
| Isometric Shaded With Edges | `IView.SetDisplayMode3(UseParent=False, Mode=3, Faceted=False, Edges=True)` | `swDisplayMode_e.swSHADED`=3 + Edges flag. `Mode=7` (`swSHADED_EDGES`) and `5` (`swViewDisplayMode_ShadedWithEdges`, a different enum) are NOT accepted (5 yields HIDDEN_GREYED=1; 7 returns False). Read back `GetDisplayMode2()==3` and `GetDisplayEdgesInShadedMode()==True`; the exported PDF contains the shaded image in the iso outline | `v7-evidence/*/verification.json` standards.iso_* |
| Broken leader, horizontal text (dimension "Custom text position") | `IDisplayDimension.SetBrokenLeader2(UseDoc=False, Broken=2)` | `swDisplayDimensionLeaderText_e.swBrokenLeaderHorizontalText`=2; read back `GetBrokenLeader2()==2`, `GetUseDocBrokenLeader()==False`. Linear dimensions read -1 (no leader text option): reported not applicable. No `SetHorizontal` effect (returns False). Doc preference 372 (`swDetailingDimensionTextAndLeaderStyle`) is read-only through `SetUserPreferenceInteger` (returns False) | standards.broken_leaders |
| Notes | `swLeaderStyle_e` has straight/bent/underlined only: no broken leader class for notes. Solid Flow creates no leadered notes (reported) | | |
| Auto Arrange Dimensions | `IModelDocExtension.AlignDimensions(swAlignDimensionType_AutoArrange=0, spacing)` after `SelectByID2(IDisplayDimension.GetNameForSelection(), "DIMENSION", ...)` (append for 2nd+). `IAnnotation.Select3` does NOT select dimensions (returns False; AlignDimensions then silently does nothing) | before/after inventory (id, value, position, attachments) in `layout_report.json` | |
| Dimension inventory | `IView.GetDisplayDimensions`, `IDisplayDimension.GetDimension2(0).SystemValue` (metres), `.GetAnnotation().GetPosition/Color/Layer/IsDangling/GetAttachedEntityCount3` | | |
| Notes inventory/move | `IView.GetNotes` (sheet pseudo-view owns sheet notes), `INote.GetAnnotation().SetPosition2` | | |
| Annotation black | layer SF_BLACK (colour 0), `IAnnotation.Color` read back == 0, PDF text colour measured | `final_measure.nonblack_text` | |
| Text extents | not available natively for dimensions: measured from the exported PDF (PyMuPDF), converted with x_m=x_pt*0.0254/72, y_m=(H-y)*0.0254/72; `check_scale` verifies page size == native sheet size | | |
| Free-view move | `IView.Position` set + `GetOutline` read-back (aligned section views may be locked) | | |
Student Edition note: every PDF carries "SOLIDWORKS Educational Product. For Instructional Use Only." (licence watermark); it is detected and excluded from collisions, never hidden.
Unresolved: ISheet.SetScale(num, den) does not change the template title block SCALE field (reads 2:1 on a 1:2 ANSI C sheet; view scales are correct).
