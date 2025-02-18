import numpy as np
# from scipy.optimize import curve_fit
# from scipy.signal import find_peaks
from scipy.interpolate import splrep, splev
import matplotlib.pyplot as plt
from scipy import ndimage
# from scipy.interpolate import interp1d, splrep, splev
# from .cross_correlation import Template
# import astropy.units as u

class Align:
    def __init__(self, dco, RVt=np.arange(-10, 10.2, 0.1)):
        self.dco = dco.copy().normalise()
        self.dco_corr = dco.copy() # for the output
        
        self.RVt = RVt
        self.pixels = np.arange(0, self.dco.nPix)
        
        # default settings
        self.shifts = np.zeros(self.dco.nObs)
        self.ccf = np.zeros((self.dco.nObs, self.RVt.size))
        self.window = 30. # pixels, for lowpass smoothing
        
        # Remove continuum
        lowpass = ndimage.gaussian_filter(self.dco.flux, [0, self.window])
        self.dco.flux /= lowpass
    
        
    @staticmethod
    def xcorr(f,g):
        nx = len(f)
        R = np.dot(f,g)/nx
        varf = np.dot(f,f)/nx
        varg = np.dot(g,g)/nx

        CC = R / np.sqrt(varf*varg)
        return CC
    
    @staticmethod
    def gaussian(x, a, x0, sigma, y0):
        return y0 + a*np.exp(-(x-x0)**2/(2*sigma**2))
    
    @staticmethod
    def clip(f, sigma=3.):
        mean, std = np.mean(f), np.std(f)
        mask = np.abs(f - mean) > std*sigma
        f[mask] = np.nan
        return f
    def get_shift(self, j, ax=None):  
        # edge = 100 # ignore the first/last N pixels
        f, g = self.dco.flux[0], self.dco.flux[j]
        f = self.clip(f)
        g = self.clip(g)
        nans = np.isnan(f)+np.isnan(g)
        # print(nans[nans==True].size)
        # fw, gw = self.dco.wlt[0, edge:-edge], self.dco.wlt[j]
        # fw = self.pixels[edge:-edge]
        fw = self.pixels[~nans]
        
        # beta = 1 - (self.RVt/c)
        cs = splrep(self.pixels[~nans], g[~nans])
        # self.ccf = np.array([self.xcorr(f, splev(fw*b, cs)) for b in beta])
        self.ccf[j] = np.array([self.xcorr(f[~nans], splev(fw+s, cs)) for s in self.RVt])
        
        if not ax is None:
            args = dict(alpha=0.5, ms=1.)
            ax.plot(self.RVt, self.ccf[j], '--o', label='Frame {:}'.format(j), **args)
            # ax.plot(self.pixels[~nans], f[~nans], label='f')
            # ax.plot(self.pixels[~nans], g[~nans], label='g')
        return self
    
    def run(self, ax=None):
        [self.get_shift(j, ax=ax) for j in range(self.dco.nObs)]
        self.shifts = self.RVt[self.ccf.argmax(axis=1)]
        return self
    
    
    def apply_shifts(self):
        
        for j in range(1,self.dco.nObs):
            cs = splrep(self.pixels, self.dco_corr.flux[j,])
            self.dco_corr.flux[j,] = splev(self.pixels + self.shifts[j], cs)
        return self
    
    def plot_results(self, outname=None):
        fig, ax = plt.subplots(1,2, figsize=(12,4))

        cmap = plt.cm.get_cmap('viridis', self.dco.nObs)
        colors = np.array([cmap(x) for x in range(self.dco.nObs)])
        for j in range(self.dco.nObs):
            ax[0].plot(self.RVt, self.ccf[j], '--o', ms=1., color=colors[j], alpha=0.35)
            ax[1].plot(j, self.shifts[j], 'o', color=colors[j], ms=5.)
          
            
        ax[1].plot(self.shifts, '--k', alpha=0.4)


        ax[0].set(xlabel='Pixel shift', ylabel='CCF')

        ylim = np.abs(ax[1].get_ylim()).max()
        ax[1].set(xlabel='Frame number', ylabel='Pixel shift', ylim=(-ylim, ylim))

        ax[1].legend()
        plt.show()    
        if outname != None:
            fig.savefig(outname)
        return None

#%% OLd version
# Works differently: searches telluric lines, fits them and compares the position
# class Align:
    
#     def __init__(self, dco=None, **header):
#         self.dco = dco
#         self.dco.pix = np.arange(0, dco.nPix)
#         if not dco is None:
#             self.temp = Template(wlt=np.arange(0,dco.nPix), flux=np.median(dco.flux,axis=0))
#             self.temp.pix = np.arange(0,dco.nPix)
#         # default parameters
#         self.edge = 12 # pixels
#         self.scale_pix = 1/20. # pixel step-size for super-sampling
#         for key in header:
#             setattr(self, key, header[key])
            
            
#     def get_peaks(self, sat=0.05, threshold=0.05):
#         '''given a normalised *emission* spectrum (Template instance), find peaks that satisfy:
#         - threshold 
#         - sat = mask out saturated peaks (below sat)
#         - edge = mask out peaks near the edges'''
# #        print(self.temp.flux)
#         sat_mask = self.temp.flux > sat
#         peaks, _ = find_peaks(-self.temp.flux[sat_mask], threshold=threshold, distance=40)
#         edges = (peaks < self.edge) + (peaks > self.temp.wlt.size+self.edge)
#         self.peaks = peaks[~edges]
#         return self   
        
        
#     def fit_lines(self, ax=None):
#         ''' must run get_peaks() first'''
        
#         if self.peaks is None:
#             print('Selecting peaks...')
#             self.get_peaks()
            
#         # self.peaks must be indices (integers), else round them to nearest int
#         if self.peaks.dtype != int:
#             self.peaks = np.rint(self.peaks).astype(int)
            
#         self.centroids = np.zeros(len(self.peaks))
            
#         for i,xcen in enumerate(self.peaks):
#             if xcen is np.nan:
#                 self.centroids[i] = np.nan
#             else:
#                 x = self.temp.wlt[xcen-self.edge:xcen+self.edge-1]
#                 y = self.temp.flux[xcen-self.edge:xcen+self.edge-1]
                
               
#                 p0 = [-0.5, self.dco.pix[xcen], 1., np.median(self.dco.flux)]
#                 xfit = np.linspace(x.min(), x.max(), 100)
#                 coeff, var_matrix = curve_fit(gauss, x, y, p0=p0)
#         #         print(coeff[1], var_matrix[1][1])
#                 if var_matrix[1][1]<0.01:
#                     self.centroids[i] = coeff[1]
    
#                     if not ax is None:
#                         fit = gauss(xfit, *coeff)
#                         line_data, = ax.plot(np.linspace(-self.edge,self.edge, y.size), y, '--o', label=np.round(coeff[1],2))
#                         ax.plot(np.linspace(-self.edge,self.edge,fit.size), fit, ls='-', c=line_data.get_color())
    
#                 else:
#                     self.centroids[i] = np.nan
                
#         return self    


#     def spline_super_sampling(self, line, flux=None, ax=None):
#         xcen_ind = np.rint(line).astype(int)   
        
#         #        x = self.temp.wlt[xcen_ind-self.edge:xcen_ind+self.edge-1]
#         pix = np.arange(0, self.dco.nPix)
#         x = pix[xcen_ind-self.edge:xcen_ind+self.edge-1]
#         y = flux[xcen_ind-self.edge:xcen_ind+self.edge-1]
        
        
#         # spline interpolate
#         cs = splrep(x, y)
#         ss_x = np.arange(x.min(), x.max(), self.scale_pix)
#         ss_line = splev(ss_x, cs)
        
#         # get refined self.centroids
#         #        print(ss_x[ss_line.argmin()])
#         min_ind = ss_line.argmin()
#         centroid_pix = ss_x[min_ind]
# #        print(line, centroid_pix)
#         #        min_frac_pix = int(np.argwhere(ss_line==ss_line.min())[0]) # fractional pixel with minimum self.dco.flux
#         #        centroid_pix = xcen_ind-self.edge + min_frac_pix*self.scale_pix
        
        
#         if ax != None:
#             ax.plot(x,y, '*', label='Data')
#             ax.plot(ss_x, ss_line,'--o', ms=1., alpha=0.4, label='Super-sampled line')
#             ax.plot(centroid_pix, ss_line.min(),'*', ms=10., alpha=0.4, label='SS centroid')
            
#         return centroid_pix
    
#     def compute_shifts(self, ax=None):
#         """
#         Function to generate the self.shift_ij variable, the matrix containing
#         the pixel shift for each frame and for 
#         each telluric line (selected by previous functions)
#         """
        
#         nans = np.isnan(self.centroids)
#         n = self.centroids[~nans].size # number of lines
#         print('Aligning with {:} reference lines'.format(n))
        
#         # initialise shift matrix (i = frames, j = lines)
#         self.shift_ij = np.zeros((self.dco.nObs, n))
    
#         for j, line in enumerate(self.centroids[~nans]):
#             master_cent = self.spline_super_sampling(line, flux=self.temp.flux)
#             for i in np.arange(0,self.dco.nObs):        
#                 cent_i = self.spline_super_sampling(line, flux=self.dco.flux[i,])
#                 self.shift_ij[i,j] = cent_i - master_cent
#         if ax != None:
#             ax.plot(np.mean(self.shift_ij, axis=1), '.', alpha=0.9)
#             ax.set(xlabel='Frame number', ylabel='Relative shift (pixels)')
        
#         return self
    
#     def apply_shifts(self, ax=None):
#         import astropy.constants as const

#         # call all required functions
#         self.get_peaks().fit_lines().compute_shifts(ax)
        
#         shifts_frame = np.mean(self.shift_ij, axis=1) # mean shift for each frame
#         beta = 1 + 2.7*shifts_frame*u.km/u.s/const.c
#         print(beta)

#         for f in range(self.dco.nObs):
#             cs = splrep(self.dco.wlt[f,], self.dco.flux[f,])
#             new_x = self.dco.wlt[f,]*beta[f]
            
#             self.dco.flux[f,] = splev(new_x, cs)
#             self.dco.wlt[f,] = new_x
#         return self
    
# class WaveSolution(Align):
#     def __init__(self, dco=None, temp=None, frame=None, **header):
#         super().__init__(dco, **header)
        
#         self.temp = temp
#         if frame is None:
#             self.spec = Template(wlt=np.median(self.dco.wlt, axis=0), flux=np.median(self.dco.flux, axis=0))
#         else:
#             self.spec = Template(wlt=self.dco.wlt[frame,], flux=self.dco.flux[frame,])
            
        
#         self.spec.pix = np.arange(0, self.spec.wlt.size)
#         self.edge = 6
#         self.scale_pix = 1/20.
        
#     def get_peaks_wave(self):
#         '''given the telluric template peaks, find the corresponding (closest) wavelength 
#         for the master spectrum'''
#         self.spec.peaks_ind = np.zeros_like(self.peaks)
#         self.spec.peaks_wave = np.zeros((self.peaks.size))
#         for i,p in enumerate(self.peaks):
#             diff = np.abs(self.spec.wlt - self.temp.wlt[p])
#             self.spec.peaks_ind[i] = int(diff.argmin())
#             self.spec.peaks_wave[i] = self.spec.wlt[diff.argmin()]
#         return self
    
#     def gaussian_centroids(self, peaks=None, tol=0.01, ax=None):
#         '''peaks are indices of the (master) peaks'''
#         import sys, warnings
#         if not sys.warnoptions:
#             warnings.simplefilter("ignore")

             
#         self.centroids = np.zeros(peaks.size)
        
#         for i,xcen in enumerate(peaks):
#             if xcen is np.nan:
#                 self.centroids[i] = np.nan
#             else:
#                 x = self.spec.pix[xcen-self.edge:xcen+self.edge]
#                 y = self.spec.flux[xcen-self.edge:xcen+self.edge]
            
           
#             p0 = [-0.5, xcen, 1., np.median(self.spec.flux)]
#             xfit = np.linspace(x.min(), x.max(), 100)
#             try:
#                 coeff, var_matrix = curve_fit(gauss, x, y, p0=p0)
#                 if var_matrix[1][1]<tol:
#                     self.centroids[i] = coeff[1]
            
#                     if not ax is None:
#                         fit = gauss(xfit, *coeff)
#                         line_data, = ax.plot(np.linspace(-self.edge,self.edge, y.size), y, '--o', label=np.round(coeff[1],2))
#                         ax.plot(np.linspace(-self.edge,self.edge,fit.size), fit, ls='-', c=line_data.get_color())
            
#                 else:
#                     self.centroids[i] = np.nan
                
#             except RuntimeError:
#                 self.centroids[i] = np.nan
           
                
#         nans = np.isnan(self.centroids)
#         self.centroids = self.centroids[~nans]
#         self.spec.peaks_ind = self.spec.peaks_ind[~nans]
#         self.spec.peaks_wave = self.spec.peaks_wave[~nans]
#         self.temp.peaks_wave = self.temp.peaks_wave[~nans]
#         return self  
    
        


# def gauss(x, *p):
#     A, mu, sigma, c = p
#     return A*np.exp(-(x-mu)**2/(2.*sigma**2)) + c    