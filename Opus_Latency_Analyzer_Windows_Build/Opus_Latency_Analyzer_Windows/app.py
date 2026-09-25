import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading, queue, csv, datetime, json, os
import numpy as np
import sounddevice as sd

FS=48000

def stimulus(duration=0.035):
    n=int(FS*duration); rng=np.random.default_rng(2026)
    x=rng.choice([-1.,1.],n)
    # Bandlimit and taper to reduce clicks and accommodate speech-oriented paths
    kernel=np.ones(5)/5; x=np.convolve(x,kernel,'same')
    x*=np.hanning(n)
    x=x/(max(abs(x))+1e-9)*0.12
    return x.astype('float32')

def estimate(ref,rx, max_delay_ms=700):
    ref=np.asarray(ref,dtype=np.float64); rx=np.asarray(rx,dtype=np.float64)
    ref-=ref.mean(); rx-=rx.mean()
    if np.max(abs(ref))<0.001 or np.max(abs(rx))<0.001: raise ValueError('Signal trop faible sur une entrée.')
    # FFT linear cross-correlation; positive lag means receiver is delayed
    n=len(ref)+len(rx)-1; fftn=1<<(n-1).bit_length()
    corr=np.fft.irfft(np.fft.rfft(rx,fftn)*np.conj(np.fft.rfft(ref,fftn)),fftn)
    maxlag=min(int(FS*max_delay_ms/1000),len(ref)-1)
    vals=corr[:maxlag+1]
    idx=int(np.argmax(np.abs(vals)))
    if idx==0 or idx==maxlag: raise ValueError('Pic de corrélation à la limite de recherche : vérifier le câblage ou la fenêtre.')
    # Peak interpolation
    a,b,c=np.abs(vals[idx-1:idx+2]); denom=a-2*b+c
    frac=0.5*(a-c)/denom if abs(denom)>1e-12 else 0.
    strength=abs(vals[idx])/(np.linalg.norm(ref)*np.linalg.norm(rx)+1e-12)
    if strength<0.08: raise ValueError('Corrélation insuffisante (%.3f) : vérifier niveaux et routage.'%strength)
    return (idx+frac)*1000/FS, strength

class App:
 def __init__(self,root):
    self.root=root; root.title('Opus Latency Analyzer — V1.0'); root.geometry('940x740')
    self.q=queue.Queue(); self.rows=[]; self.offset=0.; self.busy=False
    self.dev=tk.StringVar(); self.mode=tk.StringVar(value='LINE'); self.source=tk.StringVar(value='M-Track Duo (sortie analogique)')
    self.product=tk.StringVar(value='AuraGate → AuraSTRX'); self.firmware=tk.StringVar(); self.serial=tk.StringVar()
    self.count=tk.IntVar(value=10); self.interval=tk.DoubleVar(value=1.2); self.maxlag=tk.IntVar(value=700)
    self.status=tk.StringVar(value='Prêt. Vérifiez le câblage et les niveaux avant de lancer.'); self.stats=tk.StringVar(value='Aucune mesure')
    p=ttk.Frame(root,padding=12); p.pack(fill='both',expand=True)
    ttk.Label(p,text='OPUS  |  LATENCY ANALYZER',font=('Segoe UI',17,'bold')).pack(anchor='w')
    ttk.Label(p,text='Référence : entrée 1  •  Récepteur AuraSTRX : entrée 2  •  Acquisition commune 48 kHz').pack(anchor='w',pady=(0,12))
    cfg=ttk.LabelFrame(p,text='Configuration',padding=10); cfg.pack(fill='x')
    for i in range(4): cfg.columnconfigure(i,weight=1)
    ttk.Label(cfg,text='Périphérique audio (2 entrées / 2 sorties)').grid(row=0,column=0,columnspan=2,sticky='w')
    self.devices=ttk.Combobox(cfg,textvariable=self.dev,state='readonly',width=48); self.devices.grid(row=1,column=0,columnspan=3,sticky='ew',padx=(0,6))
    ttk.Button(cfg,text='Actualiser',command=self.refresh).grid(row=1,column=3,sticky='ew')
    ttk.Label(cfg,text='Mode entrée émetteur').grid(row=2,column=0,sticky='w',pady=(8,0))
    ttk.Label(cfg,text='Source du signal').grid(row=2,column=1,columnspan=2,sticky='w',pady=(8,0))
    ttk.Combobox(cfg,textvariable=self.mode,values=['LINE','MIC','Dante / AES67'],state='readonly').grid(row=3,column=0,sticky='ew')
    ttk.Combobox(cfg,textvariable=self.source,values=['M-Track Duo (sortie analogique)','Externe Dante / AES67 (référence analogique)'],state='readonly',width=46).grid(row=3,column=1,columnspan=3,sticky='ew')
    for col,(label,var) in enumerate([('Produit / chaîne',self.product),('Firmware',self.firmware),('N° série',self.serial)]):
        ttk.Label(cfg,text=label).grid(row=4,column=col,sticky='w',pady=(8,0)); ttk.Entry(cfg,textvariable=var).grid(row=5,column=col,sticky='ew',padx=(0,6))
    opt=ttk.Frame(p); opt.pack(fill='x',pady=10)
    for col,(label,var) in enumerate([('Nombre de mesures',self.count),('Intervalle (s)',self.interval),('Recherche max (ms)',self.maxlag)]):
        ttk.Label(opt,text=label).grid(row=0,column=col,sticky='w'); ttk.Entry(opt,textvariable=var,width=16).grid(row=1,column=col,padx=(0,16),sticky='w')
    actions=ttk.Frame(p); actions.pack(fill='x',pady=5)
    self.cal=ttk.Button(actions,text='Étalonner (boucle directe)',command=lambda:self.start(True)); self.cal.pack(side='left',padx=(0,8))
    self.run=ttk.Button(actions,text='Lancer les mesures',command=lambda:self.start(False)); self.run.pack(side='left',padx=(0,8))
    ttk.Button(actions,text='Exporter CSV',command=self.export).pack(side='left',padx=(0,8))
    ttk.Button(actions,text='Effacer historique',command=self.clear).pack(side='left')
    ttk.Label(p,textvariable=self.status,wraplength=880).pack(anchor='w',pady=8)
    ttk.Label(p,textvariable=self.stats,font=('Segoe UI',11,'bold')).pack(anchor='w',pady=(0,8))
    columns=('time','mode','latency','quality','product','firmware','serial')
    self.table=ttk.Treeview(p,columns=columns,show='headings',height=14)
    for key,label,width in [('time','Heure',125),('mode','Mode',105),('latency','Latence (ms)',115),('quality','Corrélation',105),('product','Produit',165),('firmware','Firmware',105),('serial','N° série',105)]:
        self.table.heading(key,text=label);self.table.column(key,width=width,anchor='w')
    self.table.pack(fill='both',expand=True)
    ttk.Label(p,text='Attention : la sortie casque peut saturer une entrée LINE. Démarrer volume casque au minimum, 48 V OFF, mode USB. En MIC utiliser un atténuateur adapté.',wraplength=880).pack(anchor='w',pady=8)
    self.refresh();root.after(100,self.poll)
 def refresh(self):
    try:
        ds=sd.query_devices(); self.ids=[i for i,d in enumerate(ds) if d['max_input_channels']>=2 and d['max_output_channels']>=2]
        vals=['%d : %s'%(i,ds[i]['name']) for i in self.ids];self.devices['values']=vals
        if vals: self.dev.set(next((v for v in vals if 'M-Track' in v or 'M-Audio' in v),vals[0]))
        else: self.status.set('Aucune interface audio duplex 2 entrées / 2 sorties détectée.')
    except Exception as e:self.status.set('Erreur périphériques : '+str(e))
 def start(self,cal):
    if self.busy:return
    try:
        dev=int(self.dev.get().split(' : ')[0]); count=5 if cal else int(self.count.get()); interval=float(self.interval.get());maxlag=int(self.maxlag.get())
        if not (1<=count<=10000 and .5<=interval<=30 and 20<=maxlag<=3000):raise ValueError('Paramètres hors limites.')
        if self.source.get().startswith('Externe') and not cal:
            messagebox.showinfo('Source externe','V1 : générer le même signal de test depuis la sortie M-Track vers un convertisseur analogique → Dante/AES67, ou utiliser une source externe synchronisée avec référence analogique sur entrée 1. Une source Dante indépendante sans référence corrélée n’est pas mesurable.');return
        if self.mode.get()=='Dante / AES67' and self.source.get().startswith('M-Track'):
            if not messagebox.askokcancel('Routage réseau','Confirmez qu’un convertisseur analogique → Dante/AES67 relie la sortie M-Track au réseau et qu’une copie analogique va vers entrée 1.'):return
        self.busy=True;self.cal.configure(state='disabled');self.run.configure(state='disabled')
        threading.Thread(target=self.worker,args=(dev,count,interval,maxlag,cal),daemon=True).start()
    except Exception as e:messagebox.showerror('Configuration',str(e))
 def worker(self,dev,count,interval,maxlag,cal):
    try:
        pulse=stimulus(); duration=max(1.1,interval, maxlag/1000+.3)
        n=int(FS*duration); out=np.zeros((n,2),dtype='float32');out[int(.15*FS):int(.15*FS)+len(pulse),0]=pulse
        for j in range(count):
            self.q.put(('status','Mesure %d / %d en cours…'%(j+1,count)))
            rec=sd.playrec(out,samplerate=FS,channels=2,dtype='float32',device=dev,blocking=True)
            if np.max(np.abs(rec))>.98:raise ValueError('Saturation d’une entrée : réduire le gain ou le volume casque.')
            latency,quality=estimate(rec[:,0],rec[:,1],maxlag)
            self.q.put(('result',cal,latency,quality))
        self.q.put(('done',cal))
    except Exception as e:self.q.put(('error',str(e)))
 def poll(self):
    try:
        while True:
            item=self.q.get_nowait();kind=item[0]
            if kind=='status':self.status.set(item[1])
            elif kind=='result':
                _,cal,lat,q=item
                if cal:
                    if not hasattr(self,'calvals'):self.calvals=[]
                    self.calvals.append(lat)
                else:
                    val=lat-self.offset
                    row={'time':datetime.datetime.now().isoformat(timespec='seconds'),'mode':self.mode.get(),'latency_ms':round(val,4),'correlation':round(q,4),'product':self.product.get(),'firmware':self.firmware.get(),'serial':self.serial.get(),'raw_latency_ms':round(lat,4),'calibration_ms':round(self.offset,4),'source':self.source.get()}
                    self.rows.append(row);self.table.insert('', 'end',values=(row['time'],row['mode'],f'{val:.3f}',f'{q:.3f}',row['product'],row['firmware'],row['serial']))
                    a=np.array([r['latency_ms'] for r in self.rows]);self.stats.set('Mesures : %d  |  Moyenne : %.3f ms  |  Médiane : %.3f ms  |  P95 : %.3f ms  |  Min / Max : %.3f / %.3f ms'%(len(a),a.mean(),np.median(a),np.percentile(a,95),a.min(),a.max()))
            elif kind=='done':
                if item[1]:
                    self.offset=float(np.median(self.calvals));self.status.set('Étalonnage terminé : décalage inter-voies = %.4f ms (5 mesures).'%self.offset);del self.calvals
                else:self.status.set('Campagne terminée. Exportez le CSV pour conserver les résultats.')
                self.busy=False;self.cal.configure(state='normal');self.run.configure(state='normal')
            elif kind=='error':
                self.busy=False;self.cal.configure(state='normal');self.run.configure(state='normal');self.status.set('Erreur : '+item[1]);messagebox.showerror('Mesure impossible',item[1])
    except queue.Empty:pass
    self.root.after(100,self.poll)
 def export(self):
    if not self.rows:messagebox.showinfo('Export','Aucune mesure à exporter.');return
    name=filedialog.asksaveasfilename(defaultextension='.csv',filetypes=[('CSV','*.csv')],initialfile='opus_latency_'+datetime.datetime.now().strftime('%Y%m%d_%H%M')+'.csv')
    if name:
        with open(name,'w',newline='',encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,fieldnames=list(self.rows[0]));w.writeheader();w.writerows(self.rows)
        self.status.set('Export : '+name)
 def clear(self):
    if self.busy:return
    self.rows.clear();self.table.delete(*self.table.get_children());self.stats.set('Aucune mesure');self.status.set('Historique effacé. Étalonnage conservé.')

if __name__=='__main__':
 root=tk.Tk();App(root);root.mainloop()
