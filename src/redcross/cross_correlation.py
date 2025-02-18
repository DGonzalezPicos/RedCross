import numpy as np
import matplotlib.pyplot as plt
import time
from scipy.interpolate import interp1d, splrep, splev
from copy import deepcopy
import astropy.units as u
from .datacube import Datacube
from pathos.pools import ProcessPool
from joblib import Parallel, delayed

c = 2.998e5 # km/s

class CCF(Datacube):
    mode = 'ccf'
    def __init__(self, rv=None, template=None, flux=None, **kwargs):
        self.rv = rv
        if not self.rv is None: self.dRV = np.mean(np.diff(self.rv)) # resolution
        if not template is None: self.template = template.copy()
        self.flux = flux
        
        
        self.window = 0. # high pass gaussian to apply to the template before CCF.run()
        self.n_jobs = 6 # by default
        self.spline = False # use linear interpolation unless this is True
    def normalise(self):
        self.flux = self.flux / np.median(self.flux, axis=0)
        return self  
    
    @property
    def wlt(self):
        return self.rv

    @property
    def map(self):
        return self.rv
    
    # @property
    # def snr(self):
    #     rv_abs = np.abs(self.rv)
    #     p40 = np.percentile(rv_abs, 40)
    #     bkg = self.flux[:,rv_abs > p40]
    #     ccf_1d = np.median(self.flux, axis=0)
    #     ccf_1d -= np.median(bkg)
    #     return ccf_1d / np.std(bkg)
    
    @property
    def snr(self):
        rv_abs = np.abs(self.rv)
        p40 = np.percentile(rv_abs, 40)
        bkg = self.flux[rv_abs > p40]
        ccf_snr = self.flux - np.median(bkg)
        return ccf_snr / np.std(bkg)
    
    def plot(self, ax=None, snr=False, **kwargs):
        ax = ax or plt.gca()
        if snr:
            y = self.snr
        else:
            y = self.flux
        ax.plot(self.rv, y, **kwargs)
        return ax
    

    
    def __prepare_template(self, wave):
        # start = time.time()
        # print('Computing 2D template...')
        temp2D = self.template.shift_2D(self.rv, wave)
        if self.window > 0.:
            temp2D.high_pass_gaussian(window=self.window)
        self.gTemp = temp2D.flux
        self.gTemp -= np.nanmean(self.gTemp, axis=0) 
        return self
    
    def cross_correlation(self, dco, noise='var'):
        '''Basic cross-correlation between a single-order datacube `dco` 
        and a 1D template'''
        # manage NaNs
        nans = np.isnan(dco.wlt)
        wave, flux = dco.wlt[~nans], dco.flux[:,~nans]
        f = flux - np.mean(flux)
        
        temp = self.template.copy().crop(np.min(wave), np.max(wave), eps=0.40)
        temp.flux -= np.mean(temp.flux)
    
        
        # shifts
        beta = 1 - (self.rv/c)
        # build 2D template (for every RV-shift)
        if self.spline:
            # For templates at very high resolution (~ 1e6) the spline decomposition fails
            # because the points are **too close** together (oversampled)
            cs = splrep(temp.wlt, temp.flux)
            g = np.array([splev(wave*b, cs) for b in beta])
        else:
            # when spline fails... linear interpolation doesn't
            # for very high-res templates there's no difference in the results
            _inter = interp1d(temp.wlt, temp.flux)
            g = np.array([_inter(wave*b) for b in beta])
            

        # compute the CCF-map in one step, `_i` refers to the given order 
        if noise == 'flux_err':
            noise2 = np.mean(dco.flux_err[:, ~nans]**2, axis=0)
        elif noise == 'var':
            noise2 = np.var(f, axis=0)
        elif noise == 'ones':
            noise2 = 1.
            
        # The CCF-map in one step
        return np.dot(f/noise2, g.T)


    
    def run(self, dc, apply_filter=False, noise='var', ax=None):
        self.frame = dc.frame
        start=time.time()
        
        if apply_filter:
            if hasattr(dc, 'reduction'):
                if 'high_pass_gaussian' in dc.reduction:
                    window = dc.reduction['high_pass_gaussian']['window']
                    print('Applying filter of window = {:} pixels'.format(window))
                    self.template.high_pass_gaussian(window)
    
        if len(dc.shape) > 2:
            # Iterate over orders and sum each CCF_i
            orders = np.arange(0, dc.nOrders, dtype=int)
            
            # output = Parallel(n_jobs=self.n_jobs)(delayed(self.cross_correlation)(dc.order(o), noise) for o in orders)
            output = [self.cross_correlation(dc.order(o), noise) for o in orders]
            self.flux = np.sum(np.array(output), axis=0)
           
        else: # single order CCF (or merged datacube)
            self.flux = self.cross_correlation(dc, noise)
            
        print('CCF elapsed time: {:.2f} s'.format(time.time()-start))
        # print('mean {:.4e} -- std {:.4f}'.format(np.mean(self.flux), np.std(self.flux)))
        if ax != None: self.imshow(ax=ax)
        return self
    
    
    def interpolate_to_planet(self, i):
        '''help function to parallelise `to_planet_frame` '''
        inter = interp1d(self.rv, self.flux[i,], bounds_error=False, fill_value=0.0)
        flux_i = inter(self.rv+self.planet.RV[i])
        return flux_i
    
    def to_planet_frame(self, planet, ax=None, n_jobs=6, return_self=False):
        ccf = self.copy()
        ccf.planet = planet
            
        pool = ProcessPool(nodes=n_jobs)
        flux_i = pool.amap(ccf.interpolate_to_planet, np.arange(self.nObs)).get()
        
        ccf.flux = np.array(flux_i)
        
        mask = (np.abs(ccf.rv)<np.percentile(np.abs(ccf.rv), 50))
        ccf.rv = ccf.rv[mask]
        ccf.flux = ccf.flux[:,mask]
        if ax != None: ccf.imshow(ax=ax)
        ccf.frame = 'planet'
        if return_self:
            self.rv_planet = ccf.rv
            self.flux_planet = ccf.flux
            return self
        return ccf
    
    def eclipse_label(self, planet, ax, x_rv=None, c='w'):
        x_rv = x_rv or np.percentile(self.rv, 20) # x-position of text
        self.planet = planet.copy()
        # print(self.planet.frame)

        
        phase_14 = 0.5 * ((planet.T_14) % planet.P) / planet.P
        y = [0.50 - (i*phase_14) for i in (-1,1)]
        [ax.axhline(y=y[i], ls='--', c=c) for i in range(2)]
        ax.text(s='eclipse', x=x_rv+5, y=0.50, c=c, fontsize=12)#, transform=ax.transAxes)
        ax.annotate('', xy=(x_rv, y[1]), xytext=(x_rv, y[0]), c=c, arrowprops=dict(arrowstyle='<->', ec=c))
        
        # planet trail
        mask = np.abs(self.planet.phase - 0.50) < (phase_14)
        self.planet.frame = self.frame # get the correct RV
        ax.plot(self.planet.RV[mask], self.planet.phase[mask], '--r')
        ax.plot(self.planet.RV[-10:], self.planet.phase[-10:], '--r')
        return ax
    
    
    
    def autoccf(self):
        self.flux = np.zeros_like(self.rv)
        edge = int(self.template.wlt.size / 10)

        wave, flux = self.template.wlt[edge:-edge], self.template.flux[edge:-edge]

        beta = 1 - (self.rv/c)
        cl = interp1d(self.template.wlt, self.template.flux, fill_value=np.nanmedian(flux))
        g = np.array([cl(wave*b) for b in beta])
        divide = np.sum(g, axis=1)
        self.flux = np.dot(flux, g.T) / divide
        # for i in range(self.rv.size):
        #     fxt_i = cl(wave*beta[i])
        #     self.flux[i,] = np.dot(flux, fxt_i) / np.sum(fxt_i)
        return self

                
                
class KpV:
    def __init__(self, ccf=None, planet=None, deltaRV=None, 
                 kp_radius=50., vrest_max=80., bkg=None):
        if not ccf is None:
            self.ccf = ccf.copy()
            self.planet = deepcopy(planet)
    #        self.kpVec = self.planet.Kp.value + np.arange(-kp[0], kp[0], kp[1])
    #        self.vrestVec = np.arange(-vrest[0], vrest[0]+vrest[1], vrest[1])
            self.dRV = deltaRV or ccf.dRV
    
            self.kpVec = self.planet.Kp + np.arange(-kp_radius, kp_radius, self.dRV)
            self.vrestVec = np.arange(-vrest_max, vrest_max+self.dRV, self.dRV)
            self.bkg = bkg or vrest_max*0.60
            
            try:
                self.planet.frame = self.ccf.frame
                # print(self.planet.frame)
            except:
                print('Define data rest frame...')
            self.n_jobs = 6 # for the functions that allow parallelisation
            
    def shift_vsys(self, iObs):
        print(iObs)
        outRV = self.vrestVec + self.rv_planet[iObs]
        return interp1d(self.ccf.rv, self.ccf.flux[iObs,])(outRV)    
    @property
    def snr(self):
        noise_region = np.abs(self.vrestVec)>self.bkg
        noise = np.std(self.ccf_map[:,noise_region])
        bkg = np.median(self.ccf_map[:,noise_region])
        return((self.ccf_map - bkg) / noise)
    
    @property
    def noise(self):
        '''
        Return the standard deviation of the region away from the peak i.e.
        KpV.vrestVec > KpV.bkg
        '''
        noise_region = np.abs(self.vrestVec)>self.bkg
        return np.std(self.ccf_map[:,noise_region])
    @property
    def baseline(self):
        '''
        Return the median value away from the peak i.e.
        KpV.vrestVec > KpV.bkg
        '''
        noise_region = np.abs(self.vrestVec)>self.bkg
        return np.median(self.ccf_map[:,noise_region])
        
    def run(self, ignore_eclipse=True, ax=None):
        '''Generate a Kp-Vsys map
        if snr = True, the returned values are SNR (background sub and normalised)
        else = map values'''
    
        ecl = False * np.ones_like(self.planet.RV)         
        if ignore_eclipse:   
            ecl = self.planet.mask_eclipse(return_mask=True)
            
        ccf_map = np.zeros((len(self.kpVec), len(self.vrestVec)))
        
        for ikp in range(len(self.kpVec)):            
            self.planet.Kp = self.kpVec[ikp]
            pRV = self.planet.RV
            for iObs in np.where(ecl==False)[0]:
                outRV = self.vrestVec + pRV[iObs]
                ccf_map[ikp,] += interp1d(self.ccf.rv, self.ccf.flux[iObs,])(outRV) 
        self.ccf_map = ccf_map
            
        # self.bestSNR = self.snr.max() # store info as variable
        if ax != None: self.imshow(ax=ax)
        return self
    
    
    
    def xcorr(self, f,g):
        nx = len(f)
    #        I = np.ones(nx)
    #        f -= np.dot(f,I)/nx
    #        g -= np.dot(g,I)/nx
        f -= np.mean(f)
        g -= np.mean(g)
        R = np.dot(f,g)/nx
        varf = np.dot(f,f)/nx
        varg = np.dot(g,g)/nx
    
#        CC = R / np.sqrt(varf*varg)
        log_L = -0.5*nx * np.log(varf + varg - (2*R))
        print(varf, varg, R)
        return log_L
    

        
        
    def snr_max(self, display=False):
        # Locate the peak
        self.bestSNR = self.snr.max()
        ipeak = np.where(self.snr == self.bestSNR)
        bestVr = float(self.vrestVec[ipeak[1]])
        bestKp = float(self.kpVec[ipeak[0]])
        
        if display:
            print('Peak position in Vrest = {:3.1f} km/s'.format(bestVr))
            print('Peak position in Kp = {:6.1f} km/s'.format(bestKp))
            print('Max SNR = {:3.1f}'.format(self.bestSNR))
        return(bestVr, bestKp, self.bestSNR)
    
    def plot(self, fig=None, ax=None, peak=None, vmin=None, vmax=None, label='',
             plot_peak=True, snr=True):
        lims = [self.vrestVec[0],self.vrestVec[-1],self.kpVec[0],self.kpVec[-1]]


        ax = ax or plt.gca()
        
        if snr: # Plot SNR
            y = self.snr
        else: # Plot actual values
            y = self.ccf_map
            
        vmin = vmin or y.min()
        vmax = vmax or y.max()
        
        obj = ax.imshow(y,origin='lower',extent=lims,aspect='auto', 
                        cmap='inferno',vmin=vmin,vmax=vmax, label=label)
        if not fig is None: fig.colorbar(obj, ax=ax, pad=0.05)
        ax.set_xlabel('$\Delta v$ (km/s)')
        ax.set_ylabel('K$_p$ (km/s)')

        if plot_peak:
            self.snr_at_peak(peak)
            # peak = peak or self.snr_max()
            
            # indv = np.abs(self.vrestVec - peak[0]).argmin()
            # indh = np.abs(self.kpVec - peak[1]).argmin()
        
            row = self.kpVec[self.indh]
            col = self.vrestVec[self.indv]
            line_args ={'ls':':', 'c':'white','alpha':0.35,'lw':'3.'}
            ax.axhline(y=row, **line_args)
            ax.axvline(x=col, **line_args)
            ax.scatter(col, row, marker='*', s=3., c='green',alpha=0.7,label='SNR = {:.2f}'.format(y[self.indh,self.indv]))

        return obj
    
    def snr_at_peak(self, peak=None):
        '''
        FInd the position and the SNR value of a given peak. If `peak` is a float
        it is considered the Kp value and the function searches for the peak around a range of DeltaV (< 5km/s)
        If `peak` is None, then we search for the peak around the expected planet position with a range of
        +- 10 km/s for Kp 
        +- 5 km/s for DeltaV

        Parameters
        ----------
        peak : None, float, tuple, optional
            Position of the peak. The default is None.

        Returns
        -------
            self (with relevant values stored as self.peak_pos and self.peak_snr)

        '''
        if peak is None:
            snr = self.snr
            mask_kp = np.abs(self.kpVec - self.kpVec.mean()) < 10.
            mask_dv = np.abs(self.vrestVec) < 5. # around 0.0 km/s
            snr[~mask_kp, :] = snr.min()
            snr[:, ~mask_dv] = snr.min()
            
            # max_snr = self.snr[mask_kp, mask_dv].argmax()
            indh,indv = np.where(snr == snr.max())
            self.indh, self.indv = int(indh), int(indv)
            self.peak_pos = (float(self.vrestVec[self.indv]), float(self.kpVec[self.indh]))
            
        elif isinstance(peak, float):
            self.indh = np.abs(self.kpVec - peak).argmin()
            mask_dv = np.abs(self.vrestVec) < 5. # around 0.0 km/s
            mask_indv = self.snr[self.indh, mask_dv].argmax()
            self.indv = np.argwhere(self.vrestVec == self.vrestVec[mask_dv][mask_indv])
            print(self.vrestVec[self.indv])

        elif isinstance(peak, (tuple, list)):
            self.indv = np.abs(self.vrestVec - peak[0]).argmin()
            self.indh = np.abs(self.kpVec - peak[1]).argmin()
        
        self.peak_snr = float(self.snr[self.indh,self.indv])
        return self
    
    def loc(self, dv, kp):
        peak = (dv, kp)
        indv = np.abs(self.vrestVec - peak[0]).argmin()
        indh = np.abs(self.kpVec - peak[1]).argmin()
        return float(self.ccf_map[indh, indv])
        
    def fancy_figure(self, figsize=(6,6), peak=None, vmin=None, vmax=None,
                     outname=None, title=None, display=True, **kwargs):
        '''Plot Kp-Vsys map with horizontal and vertical slices 
        snr_max=True prints the SNR for the maximum value'''
        import matplotlib.gridspec as gridspec
        fig = plt.figure(figsize=figsize)
        gs = gridspec.GridSpec(6,6)
        gs.update(wspace=0.00, hspace=0.0)
        ax1 = fig.add_subplot(gs[1:5,:5])
        ax2 = fig.add_subplot(gs[:1,:5])
        ax3 = fig.add_subplot(gs[1:5,5])
        # ax2 = fig.add_subplot(gs[0,1])
        plt.setp(ax2.get_xticklabels(), visible=False)
        plt.setp(ax3.get_yticklabels(), visible=False)
        ax3.xaxis.tick_top()
        
        eps = 0.1 * (self.snr.max()-self.snr.max())
        vmin = vmin or self.snr.min() - eps
        vmax = vmax or self.snr.max() + eps
        
        ax2.set_ylim(vmin, vmax)
        ax3.set_xlim(vmin, vmax)
            
        lims = [self.vrestVec[0],self.vrestVec[-1],self.kpVec[0],self.kpVec[-1]]

        obj = ax1.imshow(self.snr,origin='lower',extent=lims,aspect='auto', 
                         cmap='inferno', vmin=vmin, vmax=vmax)
    
        # figure settings
        ax1.set(ylabel='$K_p$ (km/s)', xlabel='$\Delta v$ (km/s)', **kwargs)
        
        # colorbar
        cax = fig.add_axes([ax3.get_position().x1+0.01,ax3.get_position().y0,
                            0.035,ax3.get_position().height])

        fig.colorbar(obj, cax=cax)
        
        if peak is None:
            peak = self.snr_max()
       # get the values     
        self.snr_at_peak(peak)
    
        row = self.kpVec[self.indh]
        col = self.vrestVec[self.indv]
        print('Horizontal slice at Kp = {:.1f} km/s'.format(row))
        print('Vertical slice at Vrest = {:.1f} km/s'.format(col))
        ax2.plot(self.vrestVec, self.snr[self.indh,:], 'gray')
        ax3.plot(self.snr[:,self.indv], self.kpVec,'gray')
        
        
    
        line_args = {'ls':':', 'c':'white','alpha':0.35,'lw':'3.', 'dashes':(0.7, 1.)}
        ax1.axhline(y=row, **line_args)
        ax1.axvline(x=col, **line_args)
        ax1.scatter(col, row, marker='*', c='red',label='SNR = {:.2f}'.format(self.peak_snr), s=6.)
        ax1.legend(handlelength=0.75)

    
        if title != None:
            fig.suptitle(title, x=0.45, y=0.915, fontsize=14)
    
        if outname != None:
            fig.savefig(outname, dpi=200, bbox_inches='tight', facecolor='white')
        if not display:
            plt.close()
        return self
    
    def copy(self):
        from copy import deepcopy
        return deepcopy(self)
    
    def save(self, outname):
        delattr(self,'planet')
        np.save(outname, self.__dict__) 
        print('{:} saved...'.format(outname))
        return None
    
    def load(self, path):
        print('Loading KpV object from...', path)
        d = np.load(path, allow_pickle=True).tolist()
        for key in d.keys():
            setattr(self, key, d[key])
        return self 
    
    @staticmethod
    def gaussian(x, a, x0, sigma, y0):
        return y0 + a*np.exp(-(x-x0)**2/(2*sigma**2))
    
    def __fit_slice(self, x,y, label):
        from scipy.optimize import curve_fit
        b = int(len(x) / 3) # ignore the first and last third of the data (consider only central region)
        popt, pcov = curve_fit(self.gaussian, x[b:-b], y[b:-b],
                               bounds=([0., x.min(), 0., -10.],
                                       [np.inf, x.max(), np.inf, np.inf]))
        # perr = np.sqrt(np.diag(pcov)) # uncertainty on the popt parameters
        print('{:} = {:.2f} km/s'.format(label, popt[1]))
        print('FWHM = {:.2f} km/s'.format(popt[2]))
        return popt
    
    def get_slice(self, axis=0, peak=None, vmin=None, vmax=None, fit=False,
                  ax=None, snr=True, auto_label=True, **kwargs):
        if snr:
            y = self.snr
            ylabel = 'SNR'
        else:
            y = self.ccf_map
            ylabel = 'CCF'
        peak = peak or self.snr_max()[:2]
        peak = peak[::-1] # invert the peak x,y
        vmin = vmin or y.min()
        vmax = vmax or y.max()
        
        x_label = [r'$K_p$', r'$\Delta v$']
        x = np.array([self.kpVec, self.vrestVec])
        
        ind = [np.abs(x[i] - peak[i]).argmin() for i in [0,1]][axis]
        x = x[::-1][axis] # get the correct x...
        
        y = np.take(y, ind, axis) # equivalent to y[ind,:] for axis=0
        
        if fit:
            popt = self.__fit_slice(x,y, x_label[::-1][axis])
        
        if ax != None:
            if auto_label:
                label = '{:}\n{:.1f} km/s'.format(x_label[axis], peak[axis])
                ax.plot(x, y, label=label, **kwargs)
            else:
                ax.plot(x, y, label=label, **kwargs)
            ax.set(ylabel=ylabel, xlabel=x_label[::-1][axis]+' (km/s)', 
                   xlim=(x.min(), x.max()), ylim=(vmin, vmax))
            # ax.set_title('CCF at {:} = {:.1f} km/s'.format(x_label[axis], peak[axis]))
            ax.axvline(x=peak[::-1][axis], ls='--',c='k', alpha=0.05)
            if fit:
                ax.plot(x, self.gaussian(x, *popt), ls='--', alpha=0.9, 
                        label='Gaussian fit', c='darkgreen')
                ax.axvline(x=popt[1], ls='--',c='darkgreen', alpha=0.7)
            ax.legend(handlelength=0.55)
            
        if fit:
            return (y, popt)
        return y
        

        
        
    
    # def plot_slice(self, mode='kp', peak=None, ax=None, vmin=None, vmax=None, 
    #                label=None, return_data=False, **kwargs):
    #     ax = ax or plt.gca()
    #     peak = peak or self.snr_max()[:2]
    #     vmin = vmin or self.snr.min()
    #     vmax = vmax or self.snr.max()
        
        
    #     if mode == 'kp':
    #         ind_kp0 = np.abs(self.kpVec - peak[1]).argmin()
    #         # print('Best Kp = {:.1f} km/s'.format(kpv_12.kpVec[ind_kp0]))
    #         y = self.snr[ind_kp0,:]
    #         label = label or 'Kp = {:.1f} km/s'.format(self.kpVec[ind_kp0])
    #         ax.plot(self.vrestVec, y, '-', label=label, **kwargs)
            
    #         ax.set(xlabel='$\Delta v$ (km/s)', ylabel='SNR', xlim=(self.vrestVec.min(), self.vrestVec.max()))
            
    #     elif mode == 'dv':
    #         ind_dv0 = np.abs(self.vrestVec - peak[0]).argmin()
    #         # print('Best Kp = {:.1f} km/s'.format(kpv_12.kpVec[ind_kp0]))
    #         y = self.snr[:,ind_dv0] # magnitude to plot / return
    #         label = label or '$\Delta$v = {:.1f} km/s'.format(self.vrestVec[ind_dv0])
    #         ax.plot(self.kpVec, y, '-', label=label, **kwargs)
    #         ax.set(xlabel='$K_p$ (km/s)', ylabel='SNR', xlim=(self.kpVec.min(), self.kpVec.max()))
            
    #     ax.set_ylim((vmin, vmax))
    #     ax.legend(frameon=False, loc='upper right')
            
    #     if return_data:
    #         return y
    #     else:
    #         return ax
        
        
        
    
    def merge_kpvs(self, kpv_list):
        new_kpv = kpv_list[0].copy()
        # add signal
        # new_kpv.snr = np.sum([kpv_list[i].snr for i in range(len(kpv_list))], axis=0)
        new_kpv.ccf_map = np.sum([(k.ccf_map - k.baseline) for k in kpv_list], axis=0)
        return new_kpv
    
    def fit_peak(self):
        self.fit = []
        for i in range(2):
            _, pfit = self.get_slice(i, fit=True)
            # print(pfit)
            self.fit.append(pfit[1:3])
        return self


    
        

    
    
    
    
    
    
    
    
    
    
    
    
    