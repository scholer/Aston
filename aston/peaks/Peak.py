import json
import numpy as np
from scipy import convolve
from pandas import Series, DataFrame
from aston.features.DBObject import DBObject
import aston.peaks.Math as peakmath
from aston.spectra.Spectrum import Spectrum
from aston.timeseries.TimeSeries import TimeSeries
from aston.spectra.Isotopes import delta13C_Santrock, delta13C_Craig
from aston.peaks.PeakFitting import fit, guess_initc
from aston.peaks.PeakModels import peak_models

peak_models = dict([(pm.__name__, pm) for pm in peak_models])


class Peak(object):
    def __init__(self, trace=None, baseline=None, peak_group=None,
                 primary_mz=None):
        self.trace = DataFrame(trace)
        self.baseline = DataFrame(baseline)
        self.peak_group = peak_group
        if primary_mz is None:
            self.primary_mz = self.trace.columns[0]

    def plot(self, mz=None, ax=None):
        pass

    def as_poly(self, mz=None, sub_base=False):
        if mz is None:
            mz = self.primary_mz
        elif mz not in self.trace.columns:
            return Series()

        t = self.trace.index
        if self.baseline is None:
            z = self.trace[mz]
        elif sub_base:
            z = np.interp(self.trace.index, self.baseline.index, \
                          self.baseline[mz])
        else:
            t = np.hstack([self.trace.index, self.baseline.index[::-1]])
            z = np.hstack([self.trace[mz], self.baseline[mz]])
        return np.vstack([t, z])

    # factor these out?
    def contains(self, x, y, mz=None):
        #from: http://www.ariel.com.au/a/python-point-int-poly.html

        # if it's not in the right time bounds, return right away
        if not (self.trace.index.values.min() < x < \
                self.trace.index.values.max()):
            return False

        data = self.as_poly(mz)
        n = len(self.trace)
        inside = False

        p1x, p1y = data[0]
        for i in range(1, n + 1):
            p2x, p2y = data[i % n]
            if y > min(p1y, p2y):
                if y <= max(p1y, p2y):
                    if x <= max(p1x, p2x):
                        if p1y != p2y:
                            xinters = (y - p1y) * (p2x - p1x) \
                                      / (p2y - p1y) + p1x
                        if p1x == p2x or x <= xinters:
                            inside = not inside
            p1x, p1y = p2x, p2y
        return inside

    def time(self):
        data = self.as_poly()
        if data[1, 0] < data[:, 0].max():
            return data[data[:, 1].argmax(), 0]
        else:  # inverted peak
            return data[data[:, 1].argmin(), 0]

    def pwhm(self):
        data = self.as_poly()
        pt1, pt2 = data[0], data[-1]

        m = (pt2[1] - pt1[1]) / (pt2[0] - pt1[0])
        avs = np.array([(pt[0], \
          (pt[1] - m * (pt[0] - pt1[0]) - pt1[1])) for pt in data])

        #calculate the height of half-max
        half_y = max(avs[:, 1]) / 2.0
        lw_x, hi_x = float('nan'), float('nan')
        #loop through all of the line segments
        for i in range(len(avs) - 1):
            #does this line segment intersect half-max?
            if (avs[i, 1] < half_y and avs[i + 1, 1] > half_y) or \
              (avs[i, 1] > half_y and avs[i + 1, 1] < half_y):
                m = (avs[i + 1, 1] - avs[i, 1]) \
                  / (avs[i + 1, 0] - avs[i, 0])
                b = (avs[i + 1, 0] * avs[i, 1] - \
                  avs[i, 0] * avs[i + 1, 1]) / \
                  (avs[i + 1, 0] - avs[i, 0])
                if np.isnan(lw_x) and np.isnan(hi_x):
                    lw_x, hi_x = (half_y - b) / m, (half_y - b) / m
                else:
                    lw_x, hi_x = min((half_y - b) / m, lw_x), \
                      max((half_y - b) / m, hi_x)
        return hi_x - lw_x

    def height(self):
        data = self.as_poly()
        return data[:, 1].max() - data[:, 1].min()

    def width(self):
        data = self.as_poly()
        return data[:, 0].max() - data[:, 0].min()

    def area(self, method='shoelace'):
        data = self.as_poly()

        # filter out any points that have a nan
        fdata = data[~np.isnan(data).any(1)]

        if method == 'shoelace':
            # up to 5e-10 diff from shoelace-slow
            csum = np.sum(np.fliplr(np.roll(fdata, 1, axis=0)) * fdata, axis=0)
            return 0.5 * np.abs(csum[0] - csum[1])
        elif method == 'shoelace-slow':
            csum = 0
            x, y = fdata[-1, :]
            for i in fdata:
                csum += i[0] * y - i[1] * x
                x, y = i
            return abs(csum / 2.)
        elif method == 'trapezoid':
            #http://en.wikipedia.org/wiki/trapezoidal_rule#non-uniform_grid
            #todo: this essentially ignores baseline data?
            #fdata[:, 1][fdata[:, 1] < 0] = 0
            #y = convolve(fdata[:, 1], [0.5, 0.5], mode='valid')

            #y = convolve(np.abs(fdata[:, 1]), [0.5, 0.5], mode='valid')

            y = convolve(fdata[:, 1], [0.5, 0.5], mode='valid')
            if y.shape[0] != fdata.shape[0] - 1:
                return 0
            return np.sum(np.diff(fdata[:, 0]) * y)
        elif method == 'sum':
            return np.sum(fdata[:, 1])


class ModelPeak(Peak):
    def __init__(self, *args, **kwargs):
        self.params = {}
        pass

    @property
    def trace(self):
        return Series()


class OldPeak(DBObject):
    def __init__(self, *args, **kwargs):
        super(Peak, self).__init__(*args, **kwargs)
        self.db_type = 'peak'
        self.childtypes = ('spectrum',)

    @property
    def data(self):
        if 'p-model' not in self.info:
            return self.rawdata

        #TODO: move this into the loop, so each mz
        # can theoretically have its own function-type
        f = peak_models.get(self.info['p-model'], None)
        if f is None:
            return self.rawdata

        all_params = json.loads(self.info['p-params'])
        y = np.empty(self.rawdata.data.shape)
        for i, params in enumerate(all_params):
            y[:, i] = f(self.rawdata.times, **params)
            y[:, i] += self.baseline(params['mz'], True)
        return TimeSeries(y, self.rawdata.times, self.rawdata.ions)

    def baseline(self, ion=None, interp=False):
        if self.info['p-baseline'] == '':
            return None
        bases = json.loads(self.info['p-baseline'])
        new_bases = bases.copy()
        #TODO: incredibly hacky and slow
        for b in bases:
            try:
                new_bases[float(b)] = bases[b]
            except:
                pass
        if ion in new_bases:
            if interp:
                base_pts = np.array(new_bases[ion]).T
                return np.interp(self.rawdata.times, *base_pts)
            else:
                return np.array(new_bases[ion])
        else:
            return None

    def set_baseline(self, ion, value=None):
        if self.info['p-baseline'] == '':
            bases = {}
        else:
            bases = json.loads(self.info['p-baseline'])
        if value is None and str(ion) in bases:
            del bases[str(ion)]
        elif value is None:
            return
        else:
            assert type(value) == np.ndarray
        bases[str(ion)] = value.tolist()
        self.info['p-baseline'] = json.dumps(bases)

    def time(self, twin=None):
        return self.rawdata.trace('!', twin=twin).time

    def trace(self, ion='!', twin=None):
        return self.rawdata.trace(ion, twin=twin).y

    def _load_info(self, fld):
        if fld == 's-mzs':
            ions = self.data.ions
            if len(ions) < 10:
                self.info[fld] = ','.join(str(i) for i in ions)
            else:
                # only display a range of the numeric ions
                ions = [i for i in ions \
                  if type(i) is int or type(i) is float]
                if len(ions) > 0:
                    self.info['s-mzs'] = str(min(ions)) + '-' + str(max(ions))
        elif fld == 'p-s-area':
            self.info[fld] = str(self.area('!'))
        elif fld == 'p-s-length':
            self.info[fld] = str(peakmath.length(self.as_poly()))
        elif fld == 'p-s-height':
            self.info[fld] = str(peakmath.height(self.as_poly()))
        elif fld == 'p-s-time':
            self.info[fld] = str(peakmath.time(self.as_poly()))
        elif fld == 'p-s-pwhm':
            self.info[fld] = str(peakmath.length(self.as_poly(), pwhm=True))
        elif fld == 'r-filename':
            prt = self.parent_of_type('file')
            self.info[fld] = prt.info['r-filename']

    def _calc_info(self, fld):
        if fld == 'p-s-pkcap':
            prt = self.parent_of_type('file')
            if prt is None:
                return ''
            t = float(prt.info['s-peaks-en']) - \
                float(prt.info['s-peaks-st'])
            return str(t / peakmath.length(self.as_poly()) + 1)
        elif fld == 'p-s-d13c':
            return self.d13C()
        return ''

    def contains(self, x, y, ion=None):
        if not self.data.has_ion(ion):
            return False
        return peakmath.contains(self.as_poly(ion), x, y)

    def as_poly(self, ion=None, sub_base=False):
        # add in the baseline on either side
        if ion is None:
            row = 0
            ion = self.data.ions[0]
        elif not self.data.has_ion(ion):
            row = 0
            ion = self.data.ions[0]
        else:
            try:
                row = self.data.ions.index(float(ion))
            except ValueError:
                row = self.data.ions.index(ion)
        pk = np.vstack([self.data.times, self.data.data.T[row]]).T
        base = self.baseline(ion)
        if sub_base:
            # this subtracts out the base line before returning it
            # it's useful for numerical fxns that don't take baseline
            if base is None:
                base_pts = np.interp(pk[:, 0], [pk[1, 0], pk[-1, 0]], \
                                     [pk[0, 1], pk[-1, 1]])
            else:
                base_pts = np.interp(pk[:, 0], *base)

            ply = np.array([pk[:, 0], pk[:, 1] - base_pts]).T
        elif base is None:
            ply = pk
        else:
            ply = np.vstack([base[0], pk, base[:0:-1]])
        return ply[np.logical_not(np.any(np.isnan(ply), axis=1))]

    def area(self, ion=None):
        if ion == '!':
            pk = self.as_poly()  # sub_base=True)
        elif not self.data.has_ion(ion):
            return 0
        else:
            pk = self.as_poly(ion)  # , sub_base=True)
        #if peakmath.area(pk, method='shoelace') / \
        #   peakmath.area(pk, method='trapezoid') != 1:
        #    print(pk)
        return peakmath.area(pk)

    def d13C(self):
        dt = self.parent_of_type('file')
        #TODO: not sure if we should do this or not
        # by not doing it, we can show relative error
        # between standard peaks
        #if self.info['p-type'] == 'Isotope Standard':
        #    return dt.info['r-d13c-std']

        # if there's no reference number, we can't do this
        try:
            float(dt.info['r-d13c-std'])
        except:
            return ''

        if self.db is not None:
            calc_meth = self.db.get_key('d13c_method', dflt='santrock')
            consts = self.db.get_key('d13c_const', dflt='Santrock')
        else:
            calc_meth, consts = 'santrock', 'Santrock'

        r45std = dt.get_point('r45std', peakmath.time(self.as_poly(44)))
        r46std = dt.get_point('r46std', peakmath.time(self.as_poly(44)))

        # if no peak has been designated as a isotope std
        if r45std == 0.0:
            return ''

        i44, i45, i46 = self.area(44), self.area(45), self.area(46)
        # if one of the areas is 0, clearly there's a problem
        if i44 * i45 * i46 == 0:
            return ''
        if calc_meth == 'craig':
            d = delta13C_Craig(i45 / i44, i46 / i44, \
              float(dt.info['r-d13c-std']), r45std, r46std)
        else:
            d = delta13C_Santrock(i45 / i44, i46 / i44, \
              float(dt.info['r-d13c-std']), r45std, r46std,
              ks=consts)

        return '{0:.3f}'.format(d)

    def as_spectrum(self, method=None):
        if method is None:
            # grab the spectrum from the same time as me
            prt = self.parent_of_type('file')
            time = peakmath.time(self.as_poly())
            data = prt.scan(time)
        elif method == 'child':
            # if there's already a sprectum assigned to
            # me, return it
            specs = self.children_of_type('spectrum')
            if len(specs) > 0:
                return specs[0]
        return Spectrum({'p-s-time': str(time)}, data)

    def update_model(self, new_f):
        INITC_ONLY = False
        self.info['p-model'] = str(new_f)
        self.info.del_items('p-s-')

        f = peak_models.get(str(new_f), None)
        all_params = []
        if f is not None:
            for i in self.rawdata.ions:
                t = self.rawdata.times
                y = self.rawdata.trace(i).y
                #TODO: subtract baseline
                #ya = x[1:-1] - np.linspace(x[0], x[-1], len(x) - 2)
                y -= self.baseline(i, interp=True)

                ts = TimeSeries(y, t)
                initc = guess_initc(ts, f, [t[y.argmax()]])
                if INITC_ONLY:
                    params = initc[0]
                else:
                    params, res = fit(ts, [f], initc)
                    params = params[0]

                params['mz'] = str(i)
                params['f'] = str(new_f)
                if not INITC_ONLY:
                    params['r^2'] = str(res['r^2'])
                all_params.append(params)

            self.info['p-params'] = json.dumps(all_params)

            get_param = lambda k, l: ','.join(str(p[k]) for p in l)
            self.info['p-s-height'] = str(get_param('h', all_params))
            #self.info['p-s-base'] = str(get_param('v', all_params))
            self.info['p-s-time'] = str(get_param('x', all_params))
            self.info['p-s-width'] = str(get_param('w', all_params))
            if not INITC_ONLY:
                self.info['p-s-model-fit'] = str(get_param('r^2', all_params))
