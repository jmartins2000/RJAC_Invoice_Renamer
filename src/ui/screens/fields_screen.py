"""Fields: what is read from each invoice, and where it goes (filename / Excel)."""
from tkinter import messagebox

import customtkinter as ctk

from src.services import fields as fieldmod
from src.ui import icons, theme as t

TYPE_LABELS = {"text": "Text", "number": "Number", "date": "Date"}


def checkbox(parent, text, value, command):
    var = ctk.BooleanVar(value=value)
    cb = ctk.CTkCheckBox(parent, text=text, variable=var, command=lambda: command(var.get()),
                         font=t.font(13), text_color=t.INK, fg_color=t.EVERGREEN, hover_color=t.EVERGREEN_HOVER,
                         border_color=t.FIELD_BORDER, border_width=2, checkbox_width=18, checkbox_height=18,
                         corner_radius=4, width=0)
    return cb


class FieldDialog(ctk.CTkToplevel):
    def __init__(self, master, field, existing_keys, on_save):
        super().__init__(master)
        self.field, self.on_save, self.existing = field, on_save, existing_keys
        self.title("Edit field" if field else "Add a field")
        self.configure(fg_color=t.SNOW)
        self.resizable(False, False)
        self.transient(master)
        w, h = 540, 470
        master.update_idletasks()
        self.geometry(f"{w}x{h}+{master.winfo_rootx() + (master.winfo_width() - w) // 2}+{master.winfo_rooty() + 80}")

        b = ctk.CTkFrame(self, fg_color="transparent")
        b.pack(fill="both", expand=True, padx=28, pady=24)
        t.label(b, "Edit field" if field else "Add a field", size=20, weight="bold").pack(anchor="w")

        t.label(b, "Name", size=12, color=t.LICHEN).pack(anchor="w", pady=(18, 6))
        self.e_label = t.entry(b, placeholder="e.g. Supplier NIF")
        self.e_label.pack(fill="x")

        t.label(b, "Type", size=12, color=t.LICHEN).pack(anchor="w", pady=(14, 6))
        self.type = ctk.CTkSegmentedButton(b, values=list(TYPE_LABELS.values()), height=32, font=t.font(13),
                                           fg_color=t.SNOWFIELD, selected_color=t.EVERGREEN,
                                           selected_hover_color=t.EVERGREEN_HOVER, unselected_color=t.SNOWFIELD,
                                           unselected_hover_color=t.FROST, text_color=t.INK, corner_radius=8)
        self.type.pack(anchor="w")

        t.label(b, "What should be read from the invoice?", size=12, color=t.LICHEN).pack(anchor="w", pady=(14, 6))
        self.instr = ctk.CTkTextbox(b, height=110, wrap="word", fg_color=t.SNOW, border_width=1,
                                    border_color=t.FIELD_BORDER, corner_radius=8, text_color=t.INK, font=t.font(13))
        self.instr.pack(fill="x")
        t.label(b, "Describe it like you would to a person: what it's called on the invoice and what to avoid.",
                size=12, color=t.LICHEN, wraplength=480).pack(anchor="w", pady=(6, 0))
        self.lbl_err = t.label(b, "", size=12, color=t.RED)
        self.lbl_err.pack(anchor="w")

        btns = ctk.CTkFrame(b, fg_color="transparent")
        btns.pack(side="bottom", fill="x")
        t.primary_button(btns, "Save", command=self._save, width=110, height=40).pack(side="right")
        t.secondary_button(btns, "Cancel", command=self.destroy, width=90, height=40).pack(side="right", padx=10)

        if field:
            self.e_label.insert(0, field.label)
            self.instr.insert("1.0", field.instructions)
            self.type.set(TYPE_LABELS[field.type])
            if field.builtin:
                self.type.configure(state="disabled")
        else:
            self.type.set("Text")
        self.after(100, self._grab)

    def _grab(self):
        try:
            self.grab_set()
            self.e_label.focus_set()
        except Exception:
            pass

    def _save(self):
        label = self.e_label.get().strip()
        instructions = self.instr.get("1.0", "end").strip()
        if not label or not instructions:
            self.lbl_err.configure(text="Please fill in the name and what should be read.")
            return
        typ = next(k for k, v in TYPE_LABELS.items() if v == self.type.get())
        if self.field:
            self.field.label, self.field.instructions = label, instructions
            if not self.field.builtin:
                self.field.type = typ
            f = self.field
        else:
            f = fieldmod.FieldDef(fieldmod.make_key(label, self.existing), label, instructions, typ,
                                  enabled=True, in_filename=False, in_excel=True, builtin=False)
        self.destroy()
        self.on_save(f, is_new=self.field is None)


class FieldsScreen(ctk.CTkFrame):
    def __init__(self, master, on_back):
        super().__init__(master, fg_color=t.SNOW, corner_radius=0)
        self.fields = fieldmod.load()

        bar = ctk.CTkFrame(self, fg_color=t.SNOW, corner_radius=0, height=62)
        bar.pack(fill="x")
        ctk.CTkButton(bar, text="", image=icons.line_icon("arrow_left"), width=34, height=34,
                      corner_radius=8, fg_color=t.SNOW, hover_color=t.SNOWFIELD, border_width=1,
                      border_color=t.FROST, command=on_back).pack(side="left", padx=(24, 14), pady=14)
        t.label(bar, "Fields", size=15, weight="bold").pack(side="left")
        t.primary_button(bar, "+ Add a field", command=self._add, height=36, size=13).pack(side="right", padx=24)
        t.divider(self).pack(fill="x")

        wrap = ctk.CTkFrame(self, fg_color="transparent", width=800)
        wrap.pack(fill="both", expand=True, pady=(28, 0))
        head = ctk.CTkFrame(wrap, fg_color="transparent", width=800)
        head.pack()
        t.label(head, "What is read from each invoice. Switch a field off to stop reading it; choose whether it "
                      "goes into the filename and the Excel. The order here is the order in the filename.",
                size=14, color=t.LICHEN, wraplength=800).pack(anchor="w")
        self.list = ctk.CTkScrollableFrame(wrap, fg_color=t.SNOW, width=800, corner_radius=0,
                                           scrollbar_button_color=t.FROST,
                                           scrollbar_button_hover_color=t.FIELD_BORDER)
        self.list.pack(fill="y", expand=True, pady=(18, 0))
        self._render()

    def _save(self):
        fieldmod.save(self.fields)

    def _render(self):
        for w in self.list.winfo_children():
            w.destroy()
        for i, f in enumerate(self.fields):
            row = ctk.CTkFrame(self.list, fg_color=t.SNOW, corner_radius=0)
            row.pack(fill="x")
            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.pack(fill="x", pady=14)

            var = ctk.BooleanVar(value=f.enabled)
            t.Toggle(inner, var, command=lambda f=f, v=var: self._set(f, "enabled", v.get())).pack(
                side="left", padx=(2, 16), anchor="n", pady=2)

            text = ctk.CTkFrame(inner, fg_color="transparent")
            text.pack(side="left", fill="x", expand=True)
            title = ctk.CTkFrame(text, fg_color="transparent")
            title.pack(anchor="w")
            t.label(title, f.label, size=15, weight="bold",
                    color=t.INK if f.enabled else t.LICHEN).pack(side="left")
            t.label(title, f"  {TYPE_LABELS[f.type]}", size=12, color=t.LICHEN).pack(side="left")
            short = f.instructions if len(f.instructions) < 110 else f.instructions[:107] + "…"
            t.label(text, short, size=12, color=t.LICHEN, wraplength=430).pack(anchor="w", pady=(2, 0))

            actions = ctk.CTkFrame(inner, fg_color="transparent")
            actions.pack(side="right", anchor="n")
            if f.enabled:
                checkbox(actions, "Filename", f.in_filename,
                         lambda v, f=f: self._set(f, "in_filename", v)).pack(side="left", padx=(0, 14))
                checkbox(actions, "Excel", f.in_excel,
                         lambda v, f=f: self._set(f, "in_excel", v)).pack(side="left", padx=(0, 14))
            for txt, cmd, ok in (("↑", lambda i=i: self._move(i, -1), i > 0),
                                 ("↓", lambda i=i: self._move(i, 1), i < len(self.fields) - 1)):
                ctk.CTkButton(actions, text=txt, width=28, height=28, corner_radius=6, fg_color=t.SNOW,
                              hover_color=t.SNOWFIELD, text_color=t.INK if ok else t.FROST, font=t.font(14),
                              command=cmd, state="normal" if ok else "disabled").pack(side="left")
            t.link_button(actions, "Edit", command=lambda f=f: self._edit(f)).pack(side="left", padx=(8, 0))
            if not f.builtin:
                ctk.CTkButton(actions, text="Delete", height=28, width=0, corner_radius=6, fg_color="transparent",
                              hover_color=t.RED_BG, text_color=t.RED, font=t.font(13, "bold"),
                              command=lambda f=f: self._delete(f)).pack(side="left")
            t.divider(row).pack(fill="x")

    def _set(self, f, attr, value):
        setattr(f, attr, value)
        if attr == "enabled" and not value:
            f.in_filename = False
        if attr == "in_filename" and not fieldmod.filename_keys(self.fields, True):
            f.in_filename = True
        self._save()
        self._render()

    def _move(self, i, d):
        j = i + d
        if 0 <= j < len(self.fields):
            self.fields[i], self.fields[j] = self.fields[j], self.fields[i]
            self._save()
            self._render()

    def _edit(self, f):
        FieldDialog(self.winfo_toplevel(), f, {x.key for x in self.fields}, self._saved)

    def _add(self):
        FieldDialog(self.winfo_toplevel(), None, {x.key for x in self.fields}, self._saved)

    def _saved(self, f, is_new):
        if is_new:
            self.fields.append(f)
        self._save()
        self._render()

    def _delete(self, f):
        if messagebox.askyesno("Delete field", f"Delete the field \"{f.label}\"?\n\n"
                                               "Values already read stay in the history."):
            self.fields.remove(f)
            self._save()
            self._render()
